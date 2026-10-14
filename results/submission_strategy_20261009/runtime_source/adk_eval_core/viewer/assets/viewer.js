(function() {
  var viewer = document.getElementById('__VIEWER_ID__');
  if (!viewer) return;

  // ── Expand/collapse toggle ────────────────────────────────────────
  viewer.querySelectorAll('.adk-viewer-entry-row').forEach(function(row) {
    row.addEventListener('click', function() {
      var entry = row.parentElement;
      var wasExpanded = entry.classList.contains('expanded');
      entry.classList.toggle('expanded', !wasExpanded);
      var toggle = row.querySelector('.adk-viewer-toggle');
      if (toggle) toggle.textContent = wasExpanded ? '▶' : '▼';
    });
  });

  // ── Filter buttons ────────────────────────────────────────────────
  viewer.querySelectorAll('.adk-viewer-filter-btn[data-type]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      btn.classList.toggle('active');
      var type = btn.getAttribute('data-type');
      var hidden = btn.classList.contains('active');
      viewer.querySelectorAll('.adk-viewer-entry').forEach(function(e) {
        if (e.getAttribute('data-type') === type) {
          e.classList.toggle('hidden', hidden);
        }
      });
    });
  });

  // ── Expand all / Collapse all ─────────────────────────────────────
  var expandBtn = viewer.querySelector('.adk-viewer-expand-all-btn');
  if (expandBtn) {
    var allExpanded = false;
    expandBtn.addEventListener('click', function() {
      allExpanded = !allExpanded;
      expandBtn.textContent = allExpanded ? 'Collapse all' : 'Expand all';
      viewer.querySelectorAll('.adk-viewer-entry').forEach(function(entry) {
        if (!entry.classList.contains('hidden')) {
          entry.classList.toggle('expanded', allExpanded);
          var toggle = entry.querySelector('.adk-viewer-toggle');
          if (toggle) toggle.textContent = allExpanded ? '▼' : '▶';
        }
      });
    });
  }
})();
