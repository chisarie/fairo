/*
 * Copyright (c) Facebook, Inc. and its affiliates.
 * A block that allows access of fields of other blocks.
 * Currently accepts Location and Time blocks as input.
 */

import * as Blockly from "blockly/core";
import "blockly/javascript";
import types, { TYPES_TO_FIELD_OPTIONS } from "../utils/types";
import customInit from "../utils/customInit";

// Programmatically generate a list of all possible options
const DEFAULT_DROPDOWN = Object.values(TYPES_TO_FIELD_OPTIONS).reduce(
  (acc, next) => {
    // add the element if it isn't already in the list
    // equality check is first element of each list, otherwise
    // it fails due to two arrays never being the "same array" by ===
    next.forEach((n) => !acc.find((el) => el && el[0] === n[0]) && acc.push(n));
    return acc;
  },
  []
);

const numberJSON = {
  type: "value_accessor",
  message0: "%1 get value of %2",
  args0: [
    {
      type: "input_value",
      name: "OBJ",
      check: [types.Location, types.Time, types.Mob, types.BlockObject],
    },
    {
      type: "field_dropdown",
      name: "FIELD",
      options: function () {
        const parent = this.getSourceBlock();
        if (!parent) return DEFAULT_DROPDOWN;

        const objInput = parent.getInputTargetBlock("OBJ");
        if (!objInput) return DEFAULT_DROPDOWN;

        // array of all output types
        const objTypesArray = objInput.outputConnection.getCheck();
        if (!objTypesArray) return DEFAULT_DROPDOWN;
        if (objTypesArray.includes(types.Location)) {
          return TYPES_TO_FIELD_OPTIONS[types.Location];
        } else if (objTypesArray.includes(types.Time)) {
          return TYPES_TO_FIELD_OPTIONS[types.Time];
        } else if (objTypesArray.includes(types.Mob)) {
          return TYPES_TO_FIELD_OPTIONS[types.Mob];
        } else if (objTypesArray.includes(types.BlockObject)) {
          return TYPES_TO_FIELD_OPTIONS[types.BlockObject];
        }

        return DEFAULT_DROPDOWN; // empty dropdown list
      },
    },
  ],
  output: null,
  helpUrl: "",
  style: "math_blocks",
  tooltip: "Get a field of a given object.",
  mutator: "labelMutator",
};

Blockly.Blocks["value_accessor"] = {
  init: function () {
    this.jsonInit(numberJSON);
    customInit(this);
  },
};

const getReferenceObjectFilters = (reference_object) => {
  const ref_obj_JS = JSON.parse(reference_object);
  if (!ref_obj_JS.reference_object)
    console.error("Accessor not provided with reference object.");
  else if (!ref_obj_JS.reference_object.filters) return {};
  else return ref_obj_JS.reference_object.filters;
};

const makeRefObjFiltersString = (reference_object, attr) => {
  const filtersJS = {
    output: {
      memory_node: "ReferenceObject",
      attribute: attr,
    },
    ...getReferenceObjectFilters(reference_object),
  };
  const filtersString = JSON.stringify(filtersJS);
  return `{ "filters": ${filtersString} }`;
};

const codeGeneratorReferenceObj = (reference_object, field) => {
  let dict = "";
  switch (field) {
    case "LOC":
      dict = `"location": ${reference_object}`;
      break;
    case "X":
      dict = makeRefObjFiltersString(reference_object, "x");
      break;
    case "Y":
      dict = makeRefObjFiltersString(reference_object, "y");
      break;
    case "Z":
      dict = makeRefObjFiltersString(reference_object, "z");
      break;
    case "NAME":
      dict = makeRefObjFiltersString(reference_object, "tag");
      break;
    case "TYPE":
      dict = makeRefObjFiltersString(reference_object, "name");
      break;
    case "SIZE":
      dict = makeRefObjFiltersString(reference_object, "size");
      break;
    case "COLOR":
      dict = makeRefObjFiltersString(reference_object, "color");
      break;
    default:
      console.warn("Unsupported field used in accessor. Returning empty form.");
  }

  return dict;
};

const codeGeneratorLocation = (reference_object, field) => {
  // format of location is `"location": { ... }` so we need to remove the key
  const dictStart = reference_object.indexOf("{");
  const dictString = reference_object.slice(dictStart);
  const dict = JSON.parse(dictString);

  if (!dict.reference_object) {
    console.warn(
      "The accessor is not yet supported for relative locations. Using default value 1."
    );
    return "1";
  } else if (dict.reference_object.special_reference === "AGENT") {
    // if agent location
    return `{ "filters": {
      "output": {
        "memory_node": "SelfNode",
        "attribute": "${field.toLowerCase()}"
    } }`;
  } else if (dict.reference_object.special_reference === "SPEAKER") {
    // if speaker location
    return `{ "filters": {
      "output": {
        "memory_node": "PlayerNode",
        "attribute": "${field.toLowerCase()}"
    } }`;
  } else {
    // otherwise, must be exact location
    // all location spans are in form "x, y, z" generated by location block
    const [
      x,
      y,
      z,
    ] = dict.reference_object.special_reference.coordinate_span.split(", ");
    return `"${field === "X" ? x : field === "Y" ? y : z}"`;
  }
};

Blockly.JavaScript["value_accessor"] = function (block) {
  // get type of obj input
  const objBlock = block.getInputTargetBlock("OBJ");
  const objTypesArray = objBlock.outputConnection.getCheck();
  if (objTypesArray.length < 0) {
    console.error("Accessor input has no type.");
    return ["", Blockly.JavaScript.ORDER_NONE];
  }
  const objType = objTypesArray[0];

  const obj = Blockly.JavaScript.valueToCode(
    block,
    "OBJ",
    Blockly.JavaScript.ORDER_NONE
  );
  const field = block.getFieldValue("FIELD");
  let dict = "";

  switch (objType) {
    case types.Mob:
    case types.BlockObject:
      dict = codeGeneratorReferenceObj(obj, field);
      break;
    case types.Location:
      dict = codeGeneratorLocation(obj, field);
      break;
    default:
      console.error("Accessor block given unsupported type.");
  }

  return [dict, Blockly.JavaScript.ORDER_NONE];
};
