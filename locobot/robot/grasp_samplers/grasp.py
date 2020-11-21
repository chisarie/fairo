#!/usr/bin/env python

# Copyright (c) Facebook, Inc. and its affiliates.

# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Grasping example with the PyRobot API.

Follow the associated README for installation instructions.
"""

import argparse
import copy
import signal
import sys
import time

import numpy as np
import rospy
from geometry_msgs.msg import Quaternion, PointStamped
from pyrobot import Robot
from tf import TransformListener
from visualization_msgs.msg import Marker
from sensor_msgs.msg import Image

from .grasp_model import GraspModel

MODEL_URL = "https://www.dropbox.com/s/jb9h6lmh9hlyslx/model.pth?dl=0"
BB_SIZE = 5
MAX_DEPTH = 3.0
BASE_FRAME = "base_link"
KINECT_FRAME = "camera_color_optical_frame"
DEFAULT_PITCH = 1.57
MIN_DEPTH = 0.1
N_SAMPLES = 100
PATCH_SIZE = 100

from pyrobot.utils.util import try_cv2_import
import os

cv2 = try_cv2_import()


# DEFAULT_PITCH_EPSILON = 0.02


class Grasper(object):
    """This class contains functionality to make the LoCoBot grasp objects
    placed in front of it."""

    def __init__(
        self,
        robot,
        url=MODEL_URL,
        model_name="model.pth",
        n_samples=N_SAMPLES,
        patch_size=PATCH_SIZE,
        *kargs,
        **kwargs
    ):
        """The constructor for :class:`Grasper` class.

        :param url: Link to the grasp model file
        :param model_name: Name of the path where the grasp model will be saved
        :param n_samples: Number of samples for the grasp sampler
        :param patch_size: Size of the patch for the grasp sampler
        :type url: string
        :type model_name: string
        :type n_samples: int
        :type patch_size: int
        """

        # TODO - use planning_mode=no_plan, its better
        self.robot = robot
        self.grasp_model = GraspModel(
            model_name=model_name, url=url, nsamples=n_samples, patchsize=patch_size
        )
        self.pregrasp_height = 0.25
        self.pregrasp_pitch = -0.2
        self.grasp_height = 0.13
        self.default_Q = Quaternion(0.0, 0.0, 0.0, 1.0)
        self.grasp_Q = Quaternion(0.0, 0.707, 0.0, 0.707)
        self.retract_position = list([-1.5, 0.5, 0.3, -0.7, 0.0])
        self.reset_pan = 0.0
        self.reset_tilt = 0.8
        self.n_tries = 5
        self._sleep_time = 3
        self._transform_listener = TransformListener()
        self.x_offset = 0.0
        self.y_offset = 0.03

        # for calibration testing
        rospy.Subscriber("/visualization_marker", Marker, self.callback)
        self.marker_data = None

    def callback(self, data):
        self.marker_data = data

    def reset(self):
        """Resets the arm to it's retract position.

        :returns: Success of the reset procedure
        :rtype: bool
        """
        success = False
        for _ in range(self.n_tries):
            self.robot.arm.go_home()
            success = self.robot.arm.set_joint_positions(self.retract_position, plan=False)
            if success:
                break
        self.robot.gripper.open()
        self.robot.camera.set_pan(self.reset_pan)
        self.robot.camera.set_tilt(self.reset_tilt)
        return success

    def _process_depth(self, cur_depth=None):
        if cur_depth is None:
            cur_depth = self.robot.camera.get_depth()
        # cur_depth = cur_depth / 1000.0  # conversion from mm to m
        cur_depth[cur_depth > MAX_DEPTH] = 0.0
        return cur_depth

    def _get_z_mean(self, depth, pt, bb=BB_SIZE):
        sum_z = 0.0
        nps = 0
        for i in range(bb * 2):
            for j in range(bb * 2):
                new_pt = [pt[0] - bb + i, pt[1] - bb + j]
                try:
                    new_z = depth[int(new_pt[0]), int(new_pt[1])]
                    if new_z > MIN_DEPTH:
                        sum_z += new_z
                        nps += 1
                except:
                    pass
        if nps == 0.0:
            return 0.0
        else:
            return sum_z / nps

    def _get_3D_camera(self, pt, norm_z=None):
        assert len(pt) == 2
        cur_depth = self._process_depth()
        z = self._get_z_mean(cur_depth, [pt[0], pt[1]])
        rospy.loginfo("depth of point is : {}".format(z))
        if z == 0.0:
            raise RuntimeError
        if norm_z is not None:
            z = z / norm_z
        u = pt[1]
        v = pt[0]
        P = copy.deepcopy(self.robot.camera.camera_P)
        rospy.loginfo("P is: {}".format(P))
        P_n = np.zeros((3, 3))
        P_n[:, :2] = P[:, :2]
        P_n[:, 2] = P[:, 3] + P[:, 2] * z
        P_n_inv = np.linalg.inv(P_n)
        temp_p = np.dot(P_n_inv, np.array([u, v, 1]))
        temp_p = temp_p / temp_p[-1]
        temp_p[-1] = z
        return temp_p

    def _convert_frames(self, pt):
        assert len(pt) == 3
        rospy.loginfo("Point to convert: {}".format(pt))
        ps = PointStamped()
        ps.header.frame_id = KINECT_FRAME
        ps.point.x, ps.point.y, ps.point.z = pt
        base_ps = self._transform_listener.transformPoint(BASE_FRAME, ps)
        rospy.loginfo(
            "transform : {}".format(
                self._transform_listener.lookupTransform(BASE_FRAME, KINECT_FRAME, rospy.Time(0))
            )
        )
        base_pt = np.array([base_ps.point.x, base_ps.point.y, base_ps.point.z])
        rospy.loginfo("Base point to convert: {}".format(base_pt))
        return base_pt

    def get_3D(self, pt, z_norm=None):
        temp_p = self._get_3D_camera(pt, z_norm)
        rospy.loginfo("temp_p: {}".format(temp_p))
        base_pt = self._convert_frames(temp_p)
        return base_pt

    def compute_grasp(self, dims=[(240, 480), (100, 540)], display_grasp=True):
        """Runs the grasp model to generate the best predicted grasp.

        :param dims: List of tuples of min and max indices of the image axis.
        :param display_grasp: Displays image of the grasp.
        :type dims: list
        :type display_grasp: bool

        :returns: Grasp configuration
        :rtype: list
        """

        img = self.robot.camera.get_rgb()
        # load random image for testgin
        img = img[dims[0][0] : dims[0][1], dims[1][0] : dims[1][1]]
        selected_grasp = list(self.grasp_model.predict(img))
        rospy.loginfo("Pixel grasp: {}".format(selected_grasp))
        # img_grasp = copy.deepcopy(selected_grasp)
        if display_grasp:
            # self.grasp_model.display_predicted_image()
            im_name = "{}.png".format(time.time())
            store_path = "../grasp_logs/" + str(int(time.time()))
            if not os.path.isdir(store_path):
                os.makedirs(store_path)
            cv2.imwrite(store_path + "/{}".format(im_name), self.grasp_model._disp_I)
        selected_grasp[0] += dims[0][0]
        selected_grasp[1] += dims[1][0]
        selected_grasp[:2] = self.get_3D(selected_grasp[:2])[:2]
        selected_grasp[2] = selected_grasp[2]
        return selected_grasp

    def _find_pose_error(self):
        """
        Figure out the camera calibration error
        error = Pose of ar maerker from camera - Pose of are marker based on arm forward kinemtics
        for this it uses the ar marker mounted in arm
        Returns:
            [np.array]: [x,y] error in me
        """

        # set the camera angle proper
        self.robot.camera.set_pan_tilt(0.0, 0.5)
        time.sleep(self._sleep_time)

        # turn the wrist around
        joint_angles = self.robot.arm.get_joint_angles()
        joint_angles[3] = -sum(joint_angles[1:3]) + self.pregrasp_pitch
        self.robot.arm.set_joint_positions(joint_angles)
        time.sleep(2 * self._sleep_time)

        # get the ar_marker pose in base frame of arm
        for _ in range(5):
            if (
                self.marker_data is None
                or (rospy.Time.now().secs - self.marker_data.header.stamp.secs) > 1.0
            ):
                rospy.loginfo("AR marker not visible, Waiting for it to come")
                joint_angles[0] -= np.deg2rad(2) * np.sign(joint_angles[0])
                self.robot.arm.set_joint_positions(joint_angles)
                time.sleep(self._sleep_time)
            else:
                rospy.loginfo("AR marker visible")
                break
        if self.marker_data is None:
            return (0, 0)

        ar_tag_pose_from_cam = self._convert_frames(
            [
                self.marker_data.pose.position.x,
                self.marker_data.pose.position.y,
                self.marker_data.pose.position.z,
            ]
        )

        # get the ar_link frame position from model
        (ar_tag_pose_from_model, _) = self._transform_listener.lookupTransform(
            BASE_FRAME, "ar_tag", rospy.Time(0)
        )

        # calculate the error
        return (np.array(ar_tag_pose_from_model) - ar_tag_pose_from_cam)[:2]

    def grasp(self, grasp_pose):
        """Performs manipulation operations to grasp at the desired pose.

        :param grasp_pose: Desired grasp pose for grasping.
        :type grasp_pose: list

        :returns: Success of grasping procedure.
        :rtype: bool
        """

        pregrasp_position = [grasp_pose[0], grasp_pose[1], self.pregrasp_height]
        grasp_angle = self.get_grasp_angle(grasp_pose)

        rospy.loginfo("Going to pre-grasp pose:\n\n {} \n".format(pregrasp_position))
        result = self.set_pose(pregrasp_position, roll=0)
        if not result:
            return False
        time.sleep(self._sleep_time)

        # find pose error the pose
        delta_x, delta_y = self._find_pose_error()
        grasp_pose[0] += delta_x + self.x_offset
        grasp_pose[1] += delta_y + self.y_offset

        # going back to grasp position
        pregrasp_position = [grasp_pose[0], grasp_pose[1], self.pregrasp_height]
        rospy.loginfo("Going to pre-grasp pose:\n\n {} \n".format(pregrasp_position))
        result = self.set_pose(pregrasp_position, roll=grasp_angle)
        if not result:
            return False
        time.sleep(self._sleep_time)

        grasp_position = [grasp_pose[0], grasp_pose[1], self.grasp_height]

        rospy.loginfo("Going to grasp pose:\n\n {} \n".format(grasp_position))
        result = self.set_pose(grasp_position, roll=grasp_angle)
        if not result:
            return False
        time.sleep(self._sleep_time)

        rospy.loginfo("Closing gripper")
        self.robot.gripper.close()
        time.sleep(self._sleep_time)

        rospy.loginfo("Going to pre-grasp pose")
        result = self.set_pose(pregrasp_position, roll=grasp_angle)
        if not result:
            return False
        time.sleep(self._sleep_time)

        """
        rospy.loginfo("Opening gripper")
        self.robot.gripper.open()
        """
        return True

    def set_pose(self, position, pitch=DEFAULT_PITCH, roll=0.0):
        """Sets desired end-effector pose.

        :param position: End-effector position to reach.
        :param pitch: Pitch angle of the end-effector.
        :param roll: Roll angle of the end-effector

        :type position: list
        :type pitch: float
        :type roll: float

        :returns: Success of pose setting process.
        :rtype: bool
        """

        success = 0
        for _ in range(self.n_tries):
            position = np.array(position)
            success = self.robot.arm.set_ee_pose_pitch_roll(
                position=position, pitch=pitch, roll=roll, plan=False, numerical=False
            )
            if success == 1:
                break
        return success

    def get_grasp_angle(self, grasp_pose):
        """Obtain normalized grasp angle from the grasp pose.

        This is needs since the grasp angle is relative to the end effector.

        :param grasp_pose: Desired grasp pose for grasping.
        :type grasp_pose: list

        :returns: Relative grasp angle
        :rtype: float
        """

        cur_angle = np.arctan2(grasp_pose[1], grasp_pose[0])
        delta_angle = grasp_pose[2] + cur_angle
        if delta_angle > np.pi / 2:
            delta_angle = delta_angle - np.pi
        elif delta_angle < -np.pi / 2:
            delta_angle = 2 * np.pi + delta_angle
        return delta_angle

    def exit(self):
        """Graceful exit."""

        rospy.loginfo("Exiting...")
        self.reset()
        sys.exit(0)

    def signal_handler(self, sig, frame):
        """Signal handling function."""
        self.exit()


def main(args):
    """This is the main function for running the grasping demo."""
    robot = Robot("locobot")
    grasper = Grasper(robot=robot, n_samples=args.n_samples, patch_size=args.patch_size)
    signal.signal(signal.SIGINT, grasper.signal_handler)
    for i in range(args.n_grasps):
        rospy.loginfo("Grasp attempt #{}".format(i + 1))
        success = grasper.reset()
        if not success:
            rospy.logerr("Arm reset failed")
            continue
        grasp_pose = grasper.compute_grasp(display_grasp=args.no_visualize)
        print("\n\n Grasp Pose: \n\n {} \n\n".format(grasp_pose))
        grasper.grasp(grasp_pose)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process args for grasper")
    parser.add_argument("--n_grasps", help="Number of grasps for inference", type=int, default=5)
    parser.add_argument(
        "--n_samples",
        help="Number of samples for a single grasp inference",
        type=int,
        default=N_SAMPLES,
    )
    parser.add_argument(
        "--patch_size", help="Size of a sampled grasp patch", type=int, default=PATCH_SIZE
    )
    parser.add_argument(
        "--no_visualize",
        help="False to visualize grasp at each iteration, True otherwise",
        dest="display_grasp",
        action="store_false",
    )
    parser.set_defaults(no_visualize=True)

    args = parser.parse_args()

    main(args)
