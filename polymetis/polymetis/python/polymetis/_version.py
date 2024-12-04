import os
import json

import polymetis

__version__ = ""

# Conda installed: Get version of conda pkg (assigned $GIT_DESCRIBE_NUMBER during build)
if "CONDA_PREFIX" in os.environ and os.environ["CONDA_PREFIX"] in polymetis.__file__:
    # Search conda pkgs for polymetis & extract version number
    stream = os.popen("conda list | grep polymetis")
    for line in stream:
        info_fields = [s for s in line.strip("\n").split(" ") if len(s) > 0]
        if info_fields[0] == "polymetis":  # pkg name == polymetis
            __version__ = info_fields[1]
            break

# Built locally: Retrive git tag description of Polymetis source code
else:
    # Navigate to polymetis pkg dir, which should be within the git repo
    original_cwd = os.getcwd()
    os.chdir(os.path.dirname(polymetis.__file__))

    # Git describe output
    stream = os.popen("git describe --tags")
    versions_list = [line for line in stream]
    version_string = versions_list[0] if len(versions_list) > 0 else "v1.0-1251-g0a01a7fa7"

    # Modify to same format as conda env variable GIT_DESCRIBE_NUMBER
    version_items = version_string.strip("\n").split("-")
    __version__ = f"{version_items[-2]}_{version_items[-1]}"

    # Reset cwd
    os.chdir(original_cwd)

if not __version__:
    raise Exception("Cannot locate Polymetis version!")
