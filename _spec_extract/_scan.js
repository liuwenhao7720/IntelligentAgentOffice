
const src = require("fs").readFileSync("/opt/IntelligentAgentOffice/web/app.js","utf8");
let depth=0, line=1, inTpl=false, inStr=null, inLC=false, inBC=false, esc=false;
const stack=[];
for (let i=0;i<src.length;i++){
  const c=src[i];
  if (c==="\n"){line++; inLC=false; continue;}
  if (inLC) continue;
  if (inBC){ if(c==="*"&&src[i+1]==="/"){inBC=false;i++;} continue;}
  if (esc){esc=false; continue;}
  if (c==="\\"){esc=true; continue;}
  if (inStr){ if(c===inStr) inStr=null; continue;}
  if (inTpl){
    if(c===String.fromCharCode(96)){inTpl=false; continue;}
    if(c==="$"&&src[i+1]==="{"){stack.push({ch:"tpl",line}); depth++; i++; inTpl=false; continue;}
    continue;
  }
  if(c==="/"&&src[i+1]==="/"){inLC=true; i++; continue;}
  if(c==="/"&&src[i+1]==="*"){inBC=true; i++; continue;}
  if(c==='"'){inStr=c; continue;}
  if(c==="'"){inStr=c; continue;}
  if(c===String.fromCharCode(96)){inTpl=true; continue;}
  if(c==="{"){depth++; stack.push({ch:"{",line});}
  if(c==="}"){depth--; const top=stack.pop(); if(top&&top.ch==="tpl"){inTpl=true;}}
  if(depth<0){console.log("NEGATIVE at line",line); process.exit(0);}
}
console.log("final depth",depth,"inTpl",inTpl,"tail",stack.slice(-6));
