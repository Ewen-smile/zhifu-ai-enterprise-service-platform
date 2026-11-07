// Zero-dependency, minimal DOM-mock smoke test for the Markdown rendering functions.
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const from = source.indexOf('// 安全版 Markdown 子集：');
const to = source.indexOf('function messageNode(role, text) {', from);
assert(from >= 0 && to > from);
class Node {
  constructor(tag, text='') {this.tag=tag;this.children=[];this.value=text;this.attrs={};this.classList={remove(){}};}
  appendChild(node) {this.children.push(node);return node;}
  replaceChildren(...children) {this.children=children;}
  hasChildNodes() {return this.children.length>0;}
  get textContent() {return this.value+this.children.map(c=>c.textContent).join('');}
  set textContent(value) {this.value=String(value);this.children=[];}
  set href(value) {this.attrs.href=value;}
  set rel(value) {this.attrs.rel=value;}
  set target(value) {this.attrs.target=value;}
  set start(value) {this.attrs.start=value;}
}
const doc = {createElement: tag=>new Node(tag),createTextNode: str=>new Node('#text',str)};
const ctx = {document:doc,URL};
vm.runInNewContext(source.slice(from,to)+'\nthis.testRender = renderSafeMarkdown;',ctx);
function walk(root) {return [root,...root.children.flatMap(walk)];}
const parent = doc.createElement('div');
ctx.testRender(parent, '## 步骤\n\n1. **重置密码**\n2. 联系 IT\n\n- 不分享**验证码**\n- 阅读 [帮助](https://example.com)\n\n```js\nalert(1)\n```\n<img src=x onerror="alert(1)">');
const nodes=walk(parent);
assert(nodes.some(n=>n.tag==='h3' && n.textContent==='步骤'));
assert.equal(nodes.filter(n=>n.tag==='li').length,4);
assert.equal(nodes.filter(n=>n.tag==='strong').length,2);
assert.equal(nodes.filter(n=>n.tag==='pre').length,1);
assert.equal(nodes.filter(n=>n.tag==='a').length,1);
assert.equal(nodes.filter(n=>n.tag==='img').length,0);
assert.equal(nodes.filter(n=>n.tag==='script').length,0);
assert(parent.textContent.includes('<img src=x onerror="alert(1)">'));
const anchor=nodes.find(n=>n.tag==='a');
assert.equal(anchor.attrs.href,'https://example.com/');
assert(anchor.attrs.rel.includes('noopener'));
console.log('Markdown JS tests passed: headings, lists, bold, code, links, XSS-safe DOM creation');
