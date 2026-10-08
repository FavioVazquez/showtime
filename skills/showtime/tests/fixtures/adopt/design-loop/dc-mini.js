// A small stand-in for the runtime of a Claude Design export, written for showtime's tests (the real one
// is not copied here). Like the real one it reads the <x-dc> template and the logic class in
// <script type="text/x-dc" data-dc-script>, moves <helmet> into the head, mounts the component on the first
// animation frame and draws the template again on every setState, filling {{name}} from renderVals().
(function () {
  'use strict';
  var tpl = '', comp = null, root = null;
  function DCLogic() { this.state = null; }
  DCLogic.prototype.setState = function (s) { this.state = Object.assign({}, this.state, s); fill(); };
  window.DCLogic = DCLogic;
  function fill() {
    var v = comp && comp.renderVals ? comp.renderVals() : {};
    root.innerHTML = tpl.replace(/\{\{\s*([\w$]+)\s*\}\}/g, function (m, k) { return v[k] === undefined ? '' : String(v[k]); });
  }
  document.addEventListener('DOMContentLoaded', function () {
    var x = document.querySelector('x-dc');
    var sc = document.querySelector('script[data-dc-script]');
    var helmet = x.querySelector('helmet');
    if (helmet) {
      Array.prototype.slice.call(helmet.children).forEach(function (c) { document.head.appendChild(c); });
      helmet.parentNode.removeChild(helmet);
    }
    tpl = x.innerHTML;
    x.parentNode.removeChild(x);
    root = document.createElement('div');
    root.id = 'dc-root';
    document.body.appendChild(root);
    // the logic is a class body: `class Component extends DCLogic { ... }`
    var Component = new Function('DCLogic', sc.textContent + '\nreturn Component;')(DCLogic);
    requestAnimationFrame(function () {
      comp = new Component();
      fill();
      if (comp.componentDidMount) comp.componentDidMount();
    });
  });
})();
