(() => {
  const tabButtons = [...document.querySelectorAll('[role="tab"]')];
  const tabPanels = [...document.querySelectorAll('[role="tabpanel"]')];

  function activateTab(button, focus = false) {
    const target = button.getAttribute('aria-controls');
    tabButtons.forEach((item) => {
      const selected = item === button;
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
    });
    tabPanels.forEach((panel) => {
      panel.hidden = panel.id !== target;
    });
    if (focus) button.focus();
  }

  tabButtons.forEach((button, index) => {
    button.addEventListener('click', () => activateTab(button));
    button.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      let next = index;
      if (event.key === 'ArrowLeft') next = (index - 1 + tabButtons.length) % tabButtons.length;
      if (event.key === 'ArrowRight') next = (index + 1) % tabButtons.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabButtons.length - 1;
      activateTab(tabButtons[next], true);
    });
  });

  document.querySelectorAll('[data-call-toggle]').forEach((button) => {
    button.addEventListener('click', () => {
      const list = button.closest('[data-call-list]');
      if (!list) return;
      const expanded = list.classList.toggle('is-expanded');
      const count = button.dataset.extraCount || '';
      button.setAttribute('aria-expanded', String(expanded));
      button.textContent = expanded ? '收合' : `展開其餘 ${count} 項`;
    });
  });

  const search = document.querySelector('#report-search');
  const broker = document.querySelector('#broker-filter');
  const asset = document.querySelector('#asset-filter');
  const dateFrom = document.querySelector('#date-from');
  const dateTo = document.querySelector('#date-to');
  const reset = document.querySelector('#filter-reset');
  const cards = [...document.querySelectorAll('[data-report-card]')];
  const count = document.querySelector('#report-count');
  const empty = document.querySelector('#report-empty');

  function normalize(value) {
    return (value || '').toLocaleLowerCase('zh-Hant').trim();
  }

  function filterReports() {
    if (!cards.length) return;
    const query = normalize(search?.value);
    const brokerValue = broker?.value || '';
    const assetValue = asset?.value || '';
    const fromValue = dateFrom?.value || '';
    const toValue = dateTo?.value || '';
    let visible = 0;

    cards.forEach((card) => {
      const matches = (!query || normalize(card.dataset.search).includes(query))
        && (!brokerValue || card.dataset.broker === brokerValue)
        && (!assetValue || (card.dataset.assets || '').split('|').includes(assetValue))
        && (!fromValue || card.dataset.date >= fromValue)
        && (!toValue || card.dataset.date <= toValue);
      card.hidden = !matches;
      if (matches) visible += 1;
    });

    if (count) count.textContent = `顯示 ${visible}／${cards.length} 份報告`;
    if (empty) empty.hidden = visible !== 0;
  }

  [search, broker, asset, dateFrom, dateTo].forEach((control) => {
    control?.addEventListener(control === search ? 'input' : 'change', filterReports);
  });
  reset?.addEventListener('click', () => {
    if (search) search.value = '';
    if (broker) broker.value = '';
    if (asset) asset.value = '';
    if (dateFrom) dateFrom.value = '';
    if (dateTo) dateTo.value = '';
    filterReports();
    search?.focus();
  });

  filterReports();
})();
