/* ============================================================
   WEB SCRAPING DASHBOARD — JavaScript
   Handles scraper control, SSE streaming, charts, table, etc.
   ============================================================ */

// ---- State ----
let allProducts = [];
let filteredProducts = [];
let currentPage = 1;
const PAGE_SIZE = 25;
let sortCol = 0;
let sortAsc = true;
let eventSource = null;

// ---- DOM Refs ----
const btnStart    = document.getElementById('btnStart');
const btnStop     = document.getElementById('btnStop');
const btnDownload = document.getElementById('btnDownload');
const statusBadge = document.getElementById('statusBadge');
const statusText  = statusBadge.querySelector('.status-text');

const progressSection = document.getElementById('progressSection');
const progressBar     = document.getElementById('progressBar');
const progressLabel   = document.getElementById('progressLabel');
const liveLog         = document.getElementById('liveLog');

const statProducts = document.getElementById('statProducts');
const statPages    = document.getElementById('statPages');
const statTime     = document.getElementById('statTime');
const statRate     = document.getElementById('statRate');

const statsSection  = document.getElementById('statsSection');
const chartsSection = document.getElementById('chartsSection');
const tableSection  = document.getElementById('tableSection');

// ---- Background Particles ----
(function initParticles() {
    const container = document.getElementById('bgParticles');
    for (let i = 0; i < 20; i++) {
        const p = document.createElement('div');
        p.classList.add('particle');
        const size = Math.random() * 4 + 2;
        p.style.width = size + 'px';
        p.style.height = size + 'px';
        p.style.left = Math.random() * 100 + '%';
        p.style.animationDuration = (Math.random() * 15 + 10) + 's';
        p.style.animationDelay = (Math.random() * 10) + 's';
        p.style.background = `rgba(${Math.random() > 0.5 ? '59,130,246' : '139,92,246'}, ${Math.random() * 0.15 + 0.05})`;
        container.appendChild(p);
    }
})();

// ---- Status Management ----
function setStatus(status, text) {
    statusBadge.className = 'status-badge ' + status;
    statusText.textContent = text || status.charAt(0).toUpperCase() + status.slice(1);
}

function setButtons(status) {
    btnStart.disabled    = (status === 'running');
    btnStop.disabled     = (status !== 'running');
    btnDownload.disabled = (status !== 'completed' && status !== 'stopped');
}

// ---- Scraper API ----
async function startScraper() {
    try {
        const res = await fetch('/api/start', { method: 'POST' });
        if (!res.ok) {
            const data = await res.json();
            logEntry(data.error || 'Failed to start', 'error');
            return;
        }
        setStatus('running', 'Running');
        setButtons('running');
        progressSection.style.display = 'block';
        liveLog.innerHTML = '';
        logEntry('Scraper started — connecting to live feed...', 'info');
        listenSSE();
    } catch (e) {
        logEntry('Network error: ' + e.message, 'error');
    }
}

async function stopScraper() {
    try {
        await fetch('/api/stop', { method: 'POST' });
        logEntry('Stop signal sent...', 'warn');
    } catch (e) {
        logEntry('Failed to stop: ' + e.message, 'error');
    }
}

function downloadCSV() {
    window.open('/api/download', '_blank');
}

// ---- Server-Sent Events ----
function listenSSE() {
    if (eventSource) eventSource.close();
    eventSource = new EventSource('/api/events');

    eventSource.onmessage = function(e) {
        const evt = JSON.parse(e.data);
        handleEvent(evt);
    };

    eventSource.onerror = function() {
        eventSource.close();
        eventSource = null;
    };
}

function handleEvent(evt) {
    const { type, data } = evt;

    switch (type) {
        case 'start':
            logEntry(`🚀 Scraping started — ${data.total_pages} pages to process`, 'info');
            break;

        case 'page_start':
            logEntry(`📄 Page ${data.page} — Fetching...`, 'info');
            break;

        case 'page_done': {
            const pct = ((data.page / 50) * 100).toFixed(1);
            progressBar.style.width = pct + '%';
            progressLabel.textContent = `${data.page} / 50 pages`;
            statProducts.textContent = data.total;
            statPages.textContent = data.page;
            statTime.textContent = formatTime(data.elapsed);
            statRate.textContent = data.elapsed > 0 ? (data.total / data.elapsed).toFixed(1) : '0';
            logEntry(`✅ Page ${data.page} — ${data.found} products (Total: ${data.total})`, 'success');
            break;
        }

        case 'page_error':
            logEntry(`❌ Page ${data.page} — ${data.message}`, 'error');
            break;

        case 'stopped':
            logEntry(`⏹ ${data.message}`, 'warn');
            setStatus('stopped', 'Stopped');
            setButtons('stopped');
            fetchAndRender();
            break;

        case 'complete':
            logEntry(`🎉 Scraping complete! ${data.total} products in ${formatTime(data.elapsed)}`, 'success');
            progressBar.style.width = '100%';
            progressLabel.textContent = '50 / 50 pages';
            setStatus('completed', 'Completed');
            setButtons('completed');
            fetchAndRender();
            break;

        case 'end':
            if (eventSource) { eventSource.close(); eventSource = null; }
            break;
    }
}

// ---- Fetch Results & Render ----
async function fetchAndRender() {
    try {
        const res = await fetch('/api/results');
        allProducts = await res.json();
        filteredProducts = [...allProducts];
        renderStats();
        renderCharts();
        renderTable();
        statsSection.style.display = 'block';
        chartsSection.style.display = 'block';
        tableSection.style.display = 'block';
    } catch (e) {
        logEntry('Failed to fetch results: ' + e.message, 'error');
    }
}

// ---- Stats Cards ----
function renderStats() {
    if (allProducts.length === 0) return;

    const prices = allProducts.map(p => p.price_inr);
    const ratings = allProducts.map(p => p.rating);
    const avg = arr => arr.reduce((a, b) => a + b, 0) / arr.length;

    document.getElementById('cardTotal').textContent = allProducts.length.toLocaleString();
    document.getElementById('cardAvgPrice').textContent = '₹' + avg(prices).toFixed(2);
    document.getElementById('cardAvgRating').textContent = avg(ratings).toFixed(2) + ' ★';
    document.getElementById('cardPriceRange').textContent = '₹' + Math.min(...prices).toFixed(0) + ' — ₹' + Math.max(...prices).toFixed(0);
}

// ---- Charts ----
function renderCharts() {
    renderRatingChart();
    renderPriceChart();
}

function renderRatingChart() {
    const counts = [0, 0, 0, 0, 0];
    allProducts.forEach(p => { if (p.rating >= 1 && p.rating <= 5) counts[p.rating - 1]++; });
    const maxCount = Math.max(...counts, 1);
    const labels = ['★', '★★', '★★★', '★★★★', '★★★★★'];

    let html = '<div class="bar-chart">';
    for (let i = 0; i < 5; i++) {
        const h = Math.max((counts[i] / maxCount) * 180, 4);
        html += `
            <div class="bar-group">
                <div class="bar bar-${i + 1}" style="height: ${h}px;">
                    <span class="bar-value">${counts[i]}</span>
                </div>
                <span class="bar-label">${labels[i]}</span>
            </div>
        `;
    }
    html += '</div>';
    document.getElementById('ratingChart').innerHTML = html;
}

function renderPriceChart() {
    // Create price histogram with 6 buckets
    const buckets = [
        { label: '₹1k–2k', min: 1000, max: 2000, count: 0 },
        { label: '₹2k–3k', min: 2000, max: 3000, count: 0 },
        { label: '₹3k–4k', min: 3000, max: 4000, count: 0 },
        { label: '₹4k–5k', min: 4000, max: 5000, count: 0 },
        { label: '₹5k–6k', min: 5000, max: 6000, count: 0 },
        { label: '₹6k+',   min: 6000, max: Infinity, count: 0 },
    ];

    allProducts.forEach(p => {
        for (const b of buckets) {
            if (p.price_inr >= b.min && p.price_inr < b.max) {
                b.count++;
                break;
            }
        }
    });

    const maxCount = Math.max(...buckets.map(b => b.count), 1);

    let html = '<div class="bar-chart">';
    buckets.forEach(b => {
        const h = Math.max((b.count / maxCount) * 180, 4);
        html += `
            <div class="bar-group">
                <div class="bar price-bar" style="height: ${h}px;">
                    <span class="bar-value">${b.count}</span>
                </div>
                <span class="bar-label">${b.label}</span>
            </div>
        `;
    });
    html += '</div>';
    document.getElementById('priceChart').innerHTML = html;
}

// ---- Data Table ----
function renderTable() {
    const tbody = document.getElementById('tableBody');
    const start = (currentPage - 1) * PAGE_SIZE;
    const page = filteredProducts.slice(start, start + PAGE_SIZE);

    tbody.innerHTML = page.map((p, i) => `
        <tr>
            <td>${start + i + 1}</td>
            <td title="${escapeHTML(p.product_name)}">${escapeHTML(p.product_name)}</td>
            <td>₹${p.price_inr.toFixed(2)}</td>
            <td><span class="stars">${'★'.repeat(p.rating)}${'☆'.repeat(5 - p.rating)}</span></td>
            <td><span class="availability-tag">${escapeHTML(p.availability)}</span></td>
        </tr>
    `).join('');

    document.getElementById('tableCount').textContent =
        `${filteredProducts.length} product${filteredProducts.length !== 1 ? 's' : ''}`;

    renderPagination();
}

function renderPagination() {
    const totalPages = Math.ceil(filteredProducts.length / PAGE_SIZE) || 1;
    const container = document.getElementById('pagination');

    // Show at most 7 page buttons
    let pages = [];
    if (totalPages <= 7) {
        for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
        pages = [1];
        let start = Math.max(2, currentPage - 1);
        let end = Math.min(totalPages - 1, currentPage + 1);
        if (currentPage <= 3) { start = 2; end = 5; }
        if (currentPage >= totalPages - 2) { start = totalPages - 4; end = totalPages - 1; }
        if (start > 2) pages.push('…');
        for (let i = start; i <= end; i++) pages.push(i);
        if (end < totalPages - 1) pages.push('…');
        pages.push(totalPages);
    }

    container.innerHTML = pages.map(p => {
        if (p === '…') return `<button disabled>…</button>`;
        return `<button class="${p === currentPage ? 'active' : ''}" onclick="goToPage(${p})">${p}</button>`;
    }).join('');
}

function goToPage(n) {
    currentPage = n;
    renderTable();
    document.getElementById('tableSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function filterTable() {
    const query = document.getElementById('searchInput').value.toLowerCase();
    const ratingVal = document.getElementById('ratingFilter').value;

    filteredProducts = allProducts.filter(p => {
        const matchesSearch = p.product_name.toLowerCase().includes(query);
        const matchesRating = (ratingVal === 'all') || (p.rating === parseInt(ratingVal));
        return matchesSearch && matchesRating;
    });

    currentPage = 1;
    renderTable();
}

function sortTable(colIndex) {
    if (sortCol === colIndex) {
        sortAsc = !sortAsc;
    } else {
        sortCol = colIndex;
        sortAsc = true;
    }

    const keys = ['index', 'product_name', 'price_inr', 'rating', 'availability'];
    const key = keys[colIndex];

    filteredProducts.sort((a, b) => {
        let va = key === 'index' ? 0 : a[key];
        let vb = key === 'index' ? 0 : b[key];
        if (typeof va === 'string') va = va.toLowerCase();
        if (typeof vb === 'string') vb = vb.toLowerCase();
        if (va < vb) return sortAsc ? -1 : 1;
        if (va > vb) return sortAsc ? 1 : -1;
        return 0;
    });

    currentPage = 1;
    renderTable();
}

// ---- Utilities ----
function logEntry(text, type = '') {
    const div = document.createElement('div');
    div.className = 'log-entry' + (type ? ' log-' + type : '');
    div.textContent = text;
    liveLog.appendChild(div);
    liveLog.scrollTop = liveLog.scrollHeight;
}

function formatTime(seconds) {
    if (seconds < 60) return seconds.toFixed(1) + 's';
    const m = Math.floor(seconds / 60);
    const s = (seconds % 60).toFixed(0);
    return `${m}m ${s}s`;
}

function escapeHTML(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ---- Init: check if there's existing data ----
(async function init() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        if (data.status === 'completed' || data.status === 'stopped') {
            setStatus(data.status, data.status === 'completed' ? 'Completed' : 'Stopped');
            setButtons(data.status);
            await fetchAndRender();
        } else if (data.status === 'running') {
            setStatus('running', 'Running');
            setButtons('running');
            progressSection.style.display = 'block';
            listenSSE();
        }
    } catch (e) {
        // Server not ready yet
    }
})();
