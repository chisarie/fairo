/*
Copyright (c) Facebook, Inc. and its affiliates.
*/
export function getInfo(){
    return {
        year: Date().split(' ')[3],
        version: "1.0.0",
        description: "Object annotation dataset generated by the data_manager tool",
        contributer: "FAIR",
        url: "NA",
        date_created: Date().split(' ').splice(1,3).join('-')
    }
}

export function clean(string){
    let s = string.toLowerCase()
    s = s.replace(/[0-9]/g, '');
    return s.trim()
}

export function area(pts){
    let sum = 0
    for(let i = 0; i < pts.length; i++){
        sum += pts[i].x * pts[(i+1) % pts.length].y - pts[i].y * pts[(i+1) % pts.length].x
    }
    return Math.abs(sum / 2.0)
}