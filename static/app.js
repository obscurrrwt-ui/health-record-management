(function () {
  // Search boxes: filter rows in a list or table by text
  document.querySelectorAll('[data-filter]').forEach(function (box) {
    box.addEventListener('input', function () {
      var target = document.querySelector(box.dataset.filter), term = box.value.toLowerCase(), shown = 0;
      if (!target) return;
      target.querySelectorAll('[data-row]').forEach(function (row) {
        var ok = row.textContent.toLowerCase().indexOf(term) !== -1;
        row.style.display = ok ? '' : 'none';
        if (ok) shown++;
      });
      var none = document.getElementById('none');
      if (none) none.classList.toggle('hide', shown > 0);
    });
  });
  // Confirm before delete
  document.querySelectorAll('form[data-confirm]').forEach(function (f) {
    f.addEventListener('submit', function (e) { if (!confirm(f.dataset.confirm)) e.preventDefault(); });
  });
  // Flash messages fade out
  setTimeout(function () {
    document.querySelectorAll('.flash').forEach(function (m) {
      m.style.opacity = 0; setTimeout(function () { m.remove(); }, 500);
    });
  }, 5000);
  // Patient picker: search the dropdown and show allergy warning
  var sel = document.getElementById('patient'), warn = document.getElementById('allergy');
  if (sel) {
    var search = document.querySelector('[data-filter-select]');
    search.addEventListener('input', function () {
      var t = search.value.toLowerCase();
      Array.prototype.forEach.call(sel.options, function (o) { o.hidden = o.value && o.text.toLowerCase().indexOf(t) === -1; });
    });
    var show = function () {
      var a = sel.options[sel.selectedIndex] && sel.options[sel.selectedIndex].dataset.allergies;
      warn.textContent = a ? 'Known allergies: ' + a : '';
      warn.classList.toggle('hide', !a);
    };
    sel.addEventListener('change', show); show();
  }
  // Prescription rows
  var list = document.getElementById('rxlist'), tpl = document.getElementById('rxtpl');
  if (list) {
    var add = function () { list.appendChild(tpl.content.cloneNode(true)); };
    document.getElementById('addrx').addEventListener('click', add);
    list.addEventListener('click', function (e) { if (e.target.hasAttribute('data-remove')) e.target.closest('.rx').remove(); });
    if (!list.children.length) add();
  }
})();
