// Global states
let activeFamily = null;
let familiesData = [];
let pollingInterval = null;
let lastLogId = 0;
let activeTab = "explorer"; // or "stats"
let globalStatsData = {};

// LocalStorage for Pinned Families
let pinnedFamilies = JSON.parse(localStorage.getItem("pinned_families") || "[]");

// Image Lightbox Zoom & Pan State
let currentModalFilename = null;
let currentModalSrc = null;
let zoomLevel = 1.0;
let translateX = 0;
let translateY = 0;
let isDragging = false;
let startX = 0, startY = 0;

// Filter State for Active Family Album
let currentFamilyFiles = [];
let albumFilterSearch = "";
let albumFilterGenus = "ALL";
let albumFilterType = "ALL";
let albumFilterFavOnly = false;

// Elements
const familyListEl = document.getElementById("family-list");
const familySearchEl = document.getElementById("family-search");
const welcomeViewEl = document.getElementById("welcome-view");
const dashboardViewEl = document.getElementById("dashboard-view");

const activeFamilyNameEl = document.getElementById("active-family-name");
const activeFamilyPathEl = document.getElementById("active-family-path");
const commonsLinkEl = document.getElementById("commons-link");

const statTotalEl = document.getElementById("stat-total");
const statCompletedEl = document.getElementById("stat-completed");
const statErrorsEl = document.getElementById("stat-errors");

const btnScanEl = document.getElementById("btn-scan");
const btnDownloadEl = document.getElementById("btn-download");
const btnPauseEl = document.getElementById("btn-pause");
const scanDepthEl = document.getElementById("scan-depth");

const treeWrapperEl = document.getElementById("tree-wrapper");
const btnTreeExpand = document.getElementById("btn-tree-expand");
const btnTreeCollapse = document.getElementById("btn-tree-collapse");

const terminalLogEl = document.getElementById("terminal-log");
const galleryGridEl = document.getElementById("gallery-grid");
const galleryCountEl = document.getElementById("gallery-count");

// Album Filter Controls
const albumSearchEl = document.getElementById("album-search");
const albumGenusFilterEl = document.getElementById("album-genus-filter");
const albumTypeFilterEl = document.getElementById("album-type-filter");
const albumFavFilterEl = document.getElementById("album-fav-filter");

// Navigation Tabs
const navBtnExplorer = document.getElementById("nav-btn-explorer");
const navBtnStats = document.getElementById("nav-btn-stats");
const globalStatsViewEl = document.getElementById("global-stats-view");

// Global stats elements
const globalScannedCountEl = document.getElementById("global-scanned-count");
const globalCommonsFilesEl = document.getElementById("global-commons-files");
const globalLocalFilesEl = document.getElementById("global-local-files");
const statsTableSearchEl = document.getElementById("stats-table-search");
const statsTableBodyEl = document.getElementById("stats-table-body");

// Batch elements
const btnBatchScanEl = document.getElementById("btn-batch-scan");
const btnBatchStopEl = document.getElementById("btn-batch-stop");
const batchScanDepthEl = document.getElementById("batch-scan-depth");
const batchProgressInfoEl = document.getElementById("batch-progress-info");
const batchCurrentFamilyEl = document.getElementById("batch-current-family");
const batchProcessedCountEl = document.getElementById("batch-processed-count");
const batchTotalCountEl = document.getElementById("batch-total-count");

// Wikipedia Elements
const btnWikiDownloadEl = document.getElementById("btn-wiki-download");
const btnWikiCustomEl = document.getElementById("btn-wiki-custom");
const wikiQueryInputEl = document.getElementById("wiki-query-input");
const wikiBodyEl = document.getElementById("wiki-body");

// Modal Elements
const imageModalEl = document.getElementById("image-modal");
const modalImgEl = document.getElementById("modal-img");
const modalPdfContainerEl = document.getElementById("modal-pdf-container");
const modalPdfIframeEl = document.getElementById("modal-pdf-iframe");
const modalZoomControlsEl = document.getElementById("modal-zoom-controls");
const modalTitleEl = document.getElementById("modal-title");
const modalLinkCommonsEl = document.getElementById("modal-link-commons");
const modalLinkMaxResEl = document.getElementById("modal-link-maxres");
const modalAiBoxEl = document.getElementById("modal-ai-box");
const modalAiContentEl = document.getElementById("modal-ai-content");
const btnModalAiClassifyEl = document.getElementById("btn-modal-ai-classify");

const btnZoomInEl = document.getElementById("btn-zoom-in");
const btnZoomOutEl = document.getElementById("btn-zoom-out");
const btnZoomResetEl = document.getElementById("btn-zoom-reset");
const zoomLevelIndicatorEl = document.getElementById("zoom-level-indicator");

// On Load
window.addEventListener("DOMContentLoaded", () => {
    loadFamilies();
    startStatusPolling();
    setupZoomAndPanEvents();
    
    // Bind search filter
    familySearchEl.addEventListener("input", filterFamilies);
    
    // Bind button actions
    btnScanEl.addEventListener("click", scanActiveFamily);
    btnDownloadEl.addEventListener("click", startDownloadActiveFamily);
    btnPauseEl.addEventListener("click", pauseDownloadActiveFamily);
    
    // Tree controls
    if (btnTreeExpand) btnTreeExpand.addEventListener("click", expandAllTreeNodes);
    if (btnTreeCollapse) btnTreeCollapse.addEventListener("click", collapseAllTreeNodes);
    
    // Album filters
    if (albumSearchEl) albumSearchEl.addEventListener("input", applyAlbumFilters);
    if (albumGenusFilterEl) albumGenusFilterEl.addEventListener("change", applyAlbumFilters);
    if (albumTypeFilterEl) albumTypeFilterEl.addEventListener("change", applyAlbumFilters);
    if (albumFavFilterEl) {
        albumFavFilterEl.addEventListener("click", () => {
            albumFilterFavOnly = !albumFilterFavOnly;
            albumFavFilterEl.classList.toggle("btn-fav-active", albumFilterFavOnly);
            applyAlbumFilters();
        });
    }
    
    // Tab switching event listeners
    navBtnExplorer.addEventListener("click", () => switchTab("explorer"));
    navBtnStats.addEventListener("click", () => switchTab("stats"));
    
    // Batch control listeners
    btnBatchScanEl.addEventListener("click", startBatchScan);
    btnBatchStopEl.addEventListener("click", stopBatchScan);
    
    // Table search filter
    statsTableSearchEl.addEventListener("input", filterStatsTable);
    
    // Wikipedia actions
    btnWikiDownloadEl.addEventListener("click", () => downloadWikipediaArticle());
    btnWikiCustomEl.addEventListener("click", toggleWikiCustomSearch);
    wikiQueryInputEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            const query = wikiQueryInputEl.value.trim();
            if (query) {
                downloadWikipediaArticle(query);
            }
        }
    });

    // AI Categorization in Modal
    if (btnModalAiClassifyEl) {
        btnModalAiClassifyEl.addEventListener("click", triggerAiClassification);
    }
    
    // Listen to hash changes for sublink routing
    window.addEventListener("hashchange", parseUrlHash);
});

// Load Sidebar Families List
async function loadFamilies() {
    try {
        const resp = await fetch("/api/families");
        if (!resp.ok) throw new Error("Error loading families");
        familiesData = await resp.json();
        renderFamiliesList();
        parseUrlHash();
    } catch (e) {
        familyListEl.innerHTML = `<li class="loading-item error">Error: ${e.message}</li>`;
    }
}

// Render Families List in Sidebar with Pinned Support
function renderFamiliesList() {
    const query = familySearchEl.value ? familySearchEl.value.toLowerCase().trim() : "";
    
    let filtered = familiesData.filter(f => f.name.toLowerCase().includes(query));
    
    // Separate pinned and unpinned
    const pinned = filtered.filter(f => pinnedFamilies.includes(f.name));
    const unpinned = filtered.filter(f => !pinnedFamilies.includes(f.name));
    
    // Sort alphabetically within each group
    pinned.sort((a, b) => a.name.localeCompare(b.name));
    unpinned.sort((a, b) => a.name.localeCompare(b.name));
    
    const sortedFamilies = [...pinned, ...unpinned];
    
    if (sortedFamilies.length === 0) {
        familyListEl.innerHTML = `<li class="loading-item">No se encontraron familias.</li>`;
        return;
    }
    
    familyListEl.innerHTML = sortedFamilies.map(f => {
        const isActive = activeFamily === f.name ? 'class="active"' : '';
        const isPinned = pinnedFamilies.includes(f.name);
        const pinnedClass = isPinned ? 'pinned' : '';
        const pinIcon = isPinned ? 'pin' : 'pin';
        
        return `
            <li ${isActive} class="${pinnedClass}" onclick="selectFamily('${f.name}')">
                <span class="family-pin-btn ${isPinned ? 'pinned' : ''}" onclick="togglePinFamily('${f.name}', event)" title="${isPinned ? 'Desanclar' : 'Anclar'}">
                    <i data-lucide="${pinIcon}" class="small-icon"></i>
                </span>
                <span class="family-name">${f.name}</span>
                <span class="family-badge">${f.downloaded}</span>
            </li>
        `;
    }).join('');
    
    lucide.createIcons();
}

function togglePinFamily(familyName, event) {
    event.stopPropagation();
    if (pinnedFamilies.includes(familyName)) {
        pinnedFamilies = pinnedFamilies.filter(name => name !== familyName);
    } else {
        pinnedFamilies.push(familyName);
    }
    localStorage.setItem("pinned_families", JSON.stringify(pinnedFamilies));
    renderFamiliesList();
}

function filterFamilies() {
    renderFamiliesList();
}

// Select Active Family
async function selectFamily(familyName) {
    activeFamily = familyName;
    updateUrlHash();
    renderFamiliesList();
    
    welcomeViewEl.classList.add("hidden");
    dashboardViewEl.classList.remove("hidden");
    
    treeWrapperEl.innerHTML = `<div class="no-tree">Haz clic en "Escanear Categoría" para listar la estructura recursiva.</div>`;
    galleryGridEl.innerHTML = `<div class="empty-gallery">Cargando galería...</div>`;
    galleryCountEl.textContent = "0 imágenes";
    
    wikiQueryInputEl.value = "";
    wikiQueryInputEl.style.display = "none";
    wikiBodyEl.innerHTML = `
        <div class="empty-wiki" style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); gap: 12px; font-style: italic; font-size: 13px;">
            <i data-lucide="book-open" style="width: 32px; height: 32px; stroke-width: 1.5;"></i>
            <span>No se ha descargado el artículo científico de Wikipedia para esta familia. Haz clic en "Descargar Artículo".</span>
        </div>
    `;
    lucide.createIcons();
    
    const info = familiesData.find(f => f.name === familyName);
    if (info) {
        activeFamilyNameEl.textContent = info.name;
        activeFamilyPathEl.textContent = info.path;
    } else {
        activeFamilyNameEl.textContent = familyName;
    }
    
    btnDownloadEl.disabled = true;
    btnPauseEl.disabled = true;
    
    await refreshActiveFamilyDetails();
}

// Refresh Active Family Details
async function refreshActiveFamilyDetails() {
    if (!activeFamily) return;
    
    try {
        const resp = await fetch(`/api/files/${activeFamily}`);
        const data = await resp.json();
        
        if (data.scanned) {
            currentFamilyFiles = data.files || [];
            
            const total = currentFamilyFiles.length;
            const completed = currentFamilyFiles.filter(f => f.status === "completed").length;
            const errors = currentFamilyFiles.filter(f => f.status === "error").length;
            
            statTotalEl.textContent = total;
            statCompletedEl.textContent = completed;
            statErrorsEl.textContent = errors;
            
            btnDownloadEl.disabled = false;
            
            // Populate Genus dropdown filter options
            populateGenusFilter(currentFamilyFiles);
            
            // Render gallery with current filters applied
            applyAlbumFilters();
            
            if (data.tree) {
                treeWrapperEl.innerHTML = renderCategoryTree(data.tree);
                lucide.createIcons();
            } else {
                treeWrapperEl.innerHTML = `<div class="no-tree">Categoría escaneada, pero el árbol no está en caché. Vuelve a escanear si deseas visualizar la estructura.</div>`;
            }
        } else {
            currentFamilyFiles = [];
            statTotalEl.textContent = "0";
            statCompletedEl.textContent = "0";
            statErrorsEl.textContent = "0";
            btnDownloadEl.disabled = true;
            galleryGridEl.innerHTML = `<div class="empty-gallery">Familia no escaneada. Escanea la categoría para buscar imágenes.</div>`;
        }
        
        if (data.wikipedia_url) {
            wikiBodyEl.innerHTML = `<iframe src="${data.wikipedia_url}" style="width: 100%; height: 100%; border: 0; background-color: #0b0f19;"></iframe>`;
            btnWikiDownloadEl.innerHTML = `<i data-lucide="refresh-cw" class="small-icon"></i> <span>Actualizar Artículo</span>`;
        } else {
            wikiBodyEl.innerHTML = `
                <div class="empty-wiki" style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); gap: 12px; font-style: italic; font-size: 13px;">
                    <i data-lucide="book-open" style="width: 32px; height: 32px; stroke-width: 1.5;"></i>
                    <span>No se ha descargado el artículo científico de Wikipedia para esta familia. Haz clic en "Descargar Artículo".</span>
                </div>
            `;
            btnWikiDownloadEl.innerHTML = `<i data-lucide="download" class="small-icon"></i> <span>Descargar Artículo</span>`;
        }
        lucide.createIcons();
        
        commonsLinkEl.href = `https://commons.wikimedia.org/wiki/Category:Botanical_illustrations_of_${encodeURIComponent(activeFamily)}`;
        
    } catch (e) {
        addTerminalLine(`[SISTEMA ERROR] Error al cargar detalles: ${e.message}`, "error");
    }
}

function populateGenusFilter(files) {
    const genera = new Set();
    files.forEach(f => {
        if (f.taxon && f.taxon.genus) {
            genera.add(f.taxon.genus);
        }
    });
    
    const sortedGenera = Array.from(genera).sort();
    albumGenusFilterEl.innerHTML = `<option value="ALL">Todos los Géneros (${sortedGenera.length})</option>` + 
        sortedGenera.map(g => `<option value="${g}">${g}</option>`).join('');
}

function applyAlbumFilters() {
    if (!currentFamilyFiles || currentFamilyFiles.length === 0) return;
    
    const query = albumSearchEl ? albumSearchEl.value.toLowerCase().trim() : "";
    const selectedGenus = albumGenusFilterEl ? albumGenusFilterEl.value : "ALL";
    const selectedType = albumTypeFilterEl ? albumTypeFilterEl.value : "ALL";
    
    let filtered = currentFamilyFiles.filter(f => f.status === "completed");
    
    if (query) {
        filtered = filtered.filter(f => f.title.toLowerCase().includes(query) || (f.taxon && f.taxon.display && f.taxon.display.toLowerCase().includes(query)));
    }
    
    if (selectedGenus !== "ALL") {
        filtered = filtered.filter(f => f.taxon && f.taxon.genus === selectedGenus);
    }
    
    if (selectedType === "IMAGE") {
        filtered = filtered.filter(f => !f.title.toLowerCase().endsWith(".pdf"));
    } else if (selectedType === "PDF") {
        filtered = filtered.filter(f => f.title.toLowerCase().endsWith(".pdf"));
    }
    
    renderGallery(filtered);
}

// Trigger Pywikibot Recursive scan on category
async function scanActiveFamily() {
    if (!activeFamily) return;
    
    btnScanEl.disabled = true;
    btnScanEl.innerHTML = `<i data-lucide="loader" class="logo-icon spin"></i> <span>Iniciando Pywikibot...</span>`;
    lucide.createIcons();
    
    addTerminalLine(`[SISTEMA] Solicitando exploración recursiva Pywikibot para la familia ${activeFamily}...`, "system");
    
    const depth = parseInt(scanDepthEl.value);
    
    try {
        const resp = await fetch(`/api/scan/${activeFamily}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ depth: depth })
        });
        
        if (!resp.ok) throw new Error("Error en el escaneo del servidor");
        
        const data = await resp.json();
        if (data.status === "started") {
            btnScanEl.innerHTML = `<i data-lucide="loader" class="logo-icon spin"></i> <span>Escaneando Pywikibot...</span>`;
            lucide.createIcons();
            addTerminalLine(`[SISTEMA] Escaneo en segundo plano iniciado. Sigue el progreso en el terminal de logs.`, "system");
        }
    } catch (e) {
        addTerminalLine(`[SISTEMA ERROR] No se pudo iniciar el escaneo: ${e.message}`, "error");
        btnScanEl.disabled = false;
        btnScanEl.innerHTML = `<i data-lucide="refresh-cw"></i> <span>Escanear Categoría</span>`;
        lucide.createIcons();
    }
}

// Render Category Tree
function renderCategoryTree(node) {
    if (!node) return "";
    
    let childrenHtml = "";
    if (node.children && node.children.length > 0) {
        childrenHtml = `<div class="tree-node-children collapsed">` + 
            node.children.map(child => renderCategoryTree(child)).join('') + 
            `</div>`;
    }
    
    const hasChildren = node.children && node.children.length > 0;
    const toggleIcon = hasChildren ? '<i data-lucide="chevron-right" class="tree-node-toggle-icon small-icon"></i>' : '';
    
    return `
        <div class="tree-node">
            <div class="tree-node-header" onclick="toggleTreeNode(this)">
                <span class="tree-node-toggle">${toggleIcon}</span>
                <i data-lucide="folder" class="tree-node-icon small-icon"></i>
                <span class="tree-node-name">${node.name}</span>
                <span class="tree-node-badge">${node.files_count} archivos</span>
            </div>
            ${childrenHtml}
        </div>
    `;
}

window.toggleTreeNode = function(header) {
    const node = header.parentElement;
    const children = node.querySelector('.tree-node-children');
    const toggleIconWrapper = header.querySelector('.tree-node-toggle');
    
    if (children) {
        children.classList.toggle('collapsed');
        const isCollapsed = children.classList.contains('collapsed');
        toggleIconWrapper.innerHTML = isCollapsed 
            ? '<i data-lucide="chevron-right" class="tree-node-toggle-icon small-icon"></i>'
            : '<i data-lucide="chevron-down" class="tree-node-toggle-icon small-icon"></i>';
        lucide.createIcons();
    }
}

function expandAllTreeNodes() {
    const allChildren = treeWrapperEl.querySelectorAll('.tree-node-children');
    allChildren.forEach(child => child.classList.remove('collapsed'));
    const allToggles = treeWrapperEl.querySelectorAll('.tree-node-toggle');
    allToggles.forEach(t => t.innerHTML = '<i data-lucide="chevron-down" class="tree-node-toggle-icon small-icon"></i>');
    lucide.createIcons();
}

function collapseAllTreeNodes() {
    const allChildren = treeWrapperEl.querySelectorAll('.tree-node-children');
    allChildren.forEach(child => child.classList.add('collapsed'));
    const allToggles = treeWrapperEl.querySelectorAll('.tree-node-toggle');
    allToggles.forEach(t => t.innerHTML = '<i data-lucide="chevron-right" class="tree-node-toggle-icon small-icon"></i>');
    lucide.createIcons();
}

// Start Downloads Action
async function startDownloadActiveFamily() {
    if (!activeFamily) return;
    
    try {
        const resp = await fetch(`/api/download/${activeFamily}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ threads: 2 })
        });
        
        const data = await resp.json();
        if (data.status === "started" || data.status === "already running") {
            btnDownloadEl.disabled = true;
            btnPauseEl.disabled = false;
        }
    } catch (e) {
        addTerminalLine(`[ERROR] No se pudo iniciar la descarga: ${e.message}`, "error");
    }
}

// Pause Downloads Action
async function pauseDownloadActiveFamily() {
    if (!activeFamily) return;
    
    try {
        const resp = await fetch(`/api/pause/${activeFamily}`, { method: "POST" });
        const data = await resp.json();
        if (data.status === "pausing") {
            btnPauseEl.disabled = true;
            btnDownloadEl.disabled = false;
        }
    } catch (e) {
        addTerminalLine(`[ERROR] No se pudo pausar la descarga: ${e.message}`, "error");
    }
}

// Render Gallery Images Grid
function renderGallery(completedFiles) {
    galleryCountEl.textContent = `${completedFiles.length} imágenes`;
    
    if (completedFiles.length === 0) {
        galleryGridEl.innerHTML = `<div class="empty-gallery">No se encontraron archivos con los filtros seleccionados.</div>`;
        return;
    }
    
    galleryGridEl.innerHTML = completedFiles.map(file => {
        const titleClean = file.title.replace("File:", "");
        const encodedFamily = encodeURIComponent(activeFamily);
        
        let base_name = sanitizeFilenameForJS(file.title);
        let ext = ".jpg";
        const dotIdx = file.title.lastIndexOf('.');
        if (dotIdx !== -1) {
            ext = file.title.substring(dotIdx).toLowerCase();
        }
        if (base_name.toLowerCase().endsWith(ext)) {
            base_name = base_name.substring(0, base_name.length - ext.length);
        }
        const imgFilename = base_name + ext;
        const encodedImageName = encodeURIComponent(imgFilename);
        
        const imgSrc = `/api/image/${encodedFamily}/${encodedImageName}`;
        
        const isPdf = ext.toLowerCase() === ".pdf";
        const badgeMarkup = isPdf ? '<span class="img-badge pdf">PDF</span>' : '';
        const imgMarkup = isPdf 
            ? `<div class="pdf-placeholder" style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; background: #1e293b; color: #ef4444; gap: 8px;"><i data-lucide="file-text" style="width: 36px; height: 36px;"></i><span style="font-size: 12px; font-weight: 600;">Documento PDF</span></div>`
            : `<img src="${imgSrc}" alt="${titleClean}" loading="lazy">`;
            
        const taxonDisplay = file.taxon && file.taxon.display ? `<div style="font-size: 11px; color: var(--accent); margin-top: 4px;">${file.taxon.display}</div>` : '';
            
        return `
            <div class="gallery-card" onclick="openImageLightbox('${imgSrc}', '${file.title.replace(/'/g, "\\'")}', '${file.description_url}', '${imgFilename}')">
                <div class="img-container">
                    ${imgMarkup}
                    ${badgeMarkup}
                </div>
                <div class="card-info">
                    <span class="card-title">${titleClean}</span>
                    ${taxonDisplay}
                </div>
            </div>
        `;
    }).join('');
    lucide.createIcons();
}

// Lightbox Modal Opener with PDF Support, Max Res, and Zoom Controls
window.openImageLightbox = function(src, title, commonsUrl, filename) {
    currentModalSrc = src;
    currentModalFilename = filename;
    modalTitleEl.textContent = title;
    modalLinkCommonsEl.href = commonsUrl;
    modalLinkMaxResEl.href = src;
    
    // Reset AI Box
    modalAiBoxEl.classList.add("hidden");
    modalAiContentEl.innerHTML = "";
    
    const isPdf = filename.toLowerCase().endsWith(".pdf") || src.toLowerCase().endsWith(".pdf");
    
    if (isPdf) {
        modalImgEl.classList.add("hidden");
        modalPdfContainerEl.classList.remove("hidden");
        modalPdfIframeEl.src = src;
        modalZoomControlsEl.style.display = "none";
    } else {
        modalPdfContainerEl.classList.add("hidden");
        modalPdfIframeEl.src = "";
        modalImgEl.classList.remove("hidden");
        modalImgEl.src = src;
        modalZoomControlsEl.style.display = "flex";
        resetZoom();
    }
    
    imageModalEl.classList.remove("hidden");
};

window.closeModal = function() {
    imageModalEl.classList.add("hidden");
    modalImgEl.src = "";
    modalPdfIframeEl.src = "";
    resetZoom();
};

// Zoom and Pan Logic
function resetZoom() {
    zoomLevel = 1.0;
    translateX = 0;
    translateY = 0;
    updateZoomTransform();
}

function updateZoomTransform() {
    modalImgEl.style.transform = `translate(${translateX}px, ${translateY}px) scale(${zoomLevel})`;
    zoomLevelIndicatorEl.textContent = `${Math.round(zoomLevel * 100)}%`;
    if (zoomLevel > 1.0) {
        modalImgEl.classList.add("zoomed");
    } else {
        modalImgEl.classList.remove("zoomed");
    }
}

function setupZoomAndPanEvents() {
    btnZoomInEl.addEventListener("click", () => {
        zoomLevel = Math.min(zoomLevel + 0.25, 4.0);
        updateZoomTransform();
    });
    
    btnZoomOutEl.addEventListener("click", () => {
        zoomLevel = Math.max(zoomLevel - 0.25, 0.5);
        if (zoomLevel <= 1.0) { translateX = 0; translateY = 0; }
        updateZoomTransform();
    });
    
    btnZoomResetEl.addEventListener("click", resetZoom);
    
    const container = document.getElementById("modal-view-container");
    container.addEventListener("wheel", (e) => {
        if (modalImgEl.classList.contains("hidden")) return;
        e.preventDefault();
        if (e.deltaY < 0) {
            zoomLevel = Math.min(zoomLevel + 0.15, 4.0);
        } else {
            zoomLevel = Math.max(zoomLevel - 0.15, 0.5);
            if (zoomLevel <= 1.0) { translateX = 0; translateY = 0; }
        }
        updateZoomTransform();
    });
    
    modalImgEl.addEventListener("mousedown", (e) => {
        if (zoomLevel <= 1.0) return;
        isDragging = true;
        startX = e.clientX - translateX;
        startY = e.clientY - translateY;
    });
    
    window.addEventListener("mousemove", (e) => {
        if (!isDragging) return;
        translateX = e.clientX - startX;
        translateY = e.clientY - startY;
        updateZoomTransform();
    });
    
    window.addEventListener("mouseup", () => {
        isDragging = false;
    });
}

// AI Classification Trigger
async function triggerAiClassification() {
    if (!activeFamily || !currentModalFilename) return;
    
    btnModalAiClassifyEl.disabled = true;
    btnModalAiClassifyEl.innerHTML = `<i data-lucide="loader" class="logo-icon spin small-icon"></i> <span>Analizando con Gemini IA...</span>`;
    lucide.createIcons();
    
    try {
        const resp = await fetch("/api/ai-classify", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ family: activeFamily, filename: currentModalFilename })
        });
        
        if (!resp.ok) {
            const errData = await resp.json();
            throw new Error(errData.error || "Error al clasificar");
        }
        
        const data = await resp.json();
        const res = data.result;
        
        let tagsHtml = "";
        if (res.tags && res.tags.length > 0) {
            tagsHtml = res.tags.map(t => `<span class="ai-tag-pill">${t}</span>`).join('');
        }
        
        modalAiContentEl.innerHTML = `
            <div style="display: flex; gap: 8px; margin-bottom: 6px;">
                <span class="ai-badge">Órgano: ${res.organ || 'No especificado'}</span>
                <span class="ai-badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border-color: rgba(16, 185, 129, 0.3);">Estilo: ${res.style || 'Ilustración'}</span>
            </div>
            <p style="margin: 4px 0 8px 0; color: #cbd5e1; font-size: 13px;">${res.description || ''}</p>
            <div style="display: flex; flex-wrap: wrap; gap: 4px;">${tagsHtml}</div>
        `;
        modalAiBoxEl.classList.remove("hidden");
        
    } catch (e) {
        alert("Error en Gemini IA: " + e.message);
    } finally {
        btnModalAiClassifyEl.disabled = false;
        btnModalAiClassifyEl.innerHTML = `<i data-lucide="sparkles" class="small-icon"></i> <span>Categorizar con IA</span>`;
        lucide.createIcons();
    }
}

// Log Appending & Status Polling Loop (with incremental since_id)
function addTerminalLine(text, style = "system") {
    const line = document.createElement("div");
    line.className = `terminal-line ${style}`;
    line.textContent = text;
    terminalLogEl.appendChild(line);
    terminalLogEl.scrollTop = terminalLogEl.scrollHeight;
}

function startStatusPolling() {
    pollingInterval = setInterval(async () => {
        try {
            const resp = await fetch(`/api/status?since_id=${lastLogId}`);
            if (!resp.ok) return;
            const data = await resp.json();
            
            // Process Logs with incremental IDs
            if (data.logs && data.logs.length > 0) {
                data.logs.forEach(item => {
                    const text = item.text || item;
                    const isErr = text.includes("[ERROR]") || text.includes("Error");
                    const isOk = text.includes("[OK]");
                    const style = isErr ? "error" : (isOk ? "ok" : "system");
                    addTerminalLine(text, style);
                    if (item.id && item.id > lastLogId) {
                        lastLogId = item.id;
                    }
                });
            }
            
            // Active Tasks Progress
            if (activeFamily) {
                const activeFamilyCap = activeFamily.capitalize();
                
                const task = data.tasks.find(t => t.family === activeFamilyCap);
                if (task) {
                    statTotalEl.textContent = task.total;
                    statCompletedEl.textContent = task.completed;
                    statErrorsEl.textContent = task.errors;
                    
                    if (task.status === "running") {
                        btnDownloadEl.disabled = true;
                        btnPauseEl.disabled = false;
                    } else {
                        btnDownloadEl.disabled = false;
                        btnPauseEl.disabled = true;
                    }
                    
                    const currentCount = parseInt(galleryCountEl.textContent) || 0;
                    if (task.completed > currentCount && (task.completed - currentCount) >= 5) {
                        refreshActiveFamilyDetails();
                        loadFamilies();
                    }
                }
                
                // Background scans progress
                if (data.scans && data.scans[activeFamilyCap]) {
                    const scan = data.scans[activeFamilyCap];
                    if (scan.status === "running") {
                        btnScanEl.disabled = true;
                        btnScanEl.innerHTML = `<i data-lucide="loader" class="logo-icon spin"></i> <span>Escaneando...</span>`;
                        lucide.createIcons();
                    } else if (scan.status === "completed") {
                        if (btnScanEl.disabled) {
                            btnScanEl.disabled = false;
                            btnScanEl.innerHTML = `<i data-lucide="refresh-cw"></i> <span>Escanear Categoría</span>`;
                            lucide.createIcons();
                            
                            if (scan.tree) {
                                treeWrapperEl.innerHTML = renderCategoryTree(scan.tree);
                                lucide.createIcons();
                            }
                            
                            addTerminalLine(`[SISTEMA] Escaneo completado con éxito. Se detectaron ${scan.files_count} archivos.`, "ok");
                            refreshActiveFamilyDetails();
                            loadFamilies();
                        }
                    } else if (scan.status === "failed") {
                        if (btnScanEl.disabled) {
                            btnScanEl.disabled = false;
                            btnScanEl.innerHTML = `<i data-lucide="refresh-cw"></i> <span>Escanear Categoría</span>`;
                            lucide.createIcons();
                            addTerminalLine(`[SISTEMA ERROR] Escaneo fallido: ${scan.error}`, "error");
                            treeWrapperEl.innerHTML = `<div class="no-tree text-danger">Error: ${scan.error}</div>`;
                        }
                    }
                }
            }
            
            // Batch scan status
            if (data.batch_scan) {
                const batch = data.batch_scan;
                if (batch.active) {
                    btnBatchScanEl.disabled = true;
                    btnBatchStopEl.disabled = false;
                    batchProgressInfoEl.style.display = "block";
                    batchCurrentFamilyEl.textContent = batch.current_family || "Iniciando...";
                    batchProcessedCountEl.textContent = batch.processed;
                    batchTotalCountEl.textContent = batch.total;
                    
                    if (activeTab === "stats" && Math.random() < 0.2) {
                        loadGlobalStats();
                    }
                } else {
                    if (btnBatchScanEl.disabled) {
                        btnBatchScanEl.disabled = false;
                        btnBatchStopEl.disabled = true;
                        batchProgressInfoEl.style.display = "none";
                        if (activeTab === "stats") {
                            loadGlobalStats();
                        }
                    }
                }
            }
        } catch (e) {
            console.error("Error polling status:", e);
        }
    }, 1000);
}

// Tab Switching with Clean Lucide Icon Re-rendering
function switchTab(tabName) {
    activeTab = tabName;
    updateUrlHash();
    
    if (tabName === "explorer") {
        navBtnExplorer.classList.add("active");
        navBtnStats.classList.remove("active");
        
        globalStatsViewEl.classList.add("hidden");
        if (!activeFamily) {
            welcomeViewEl.classList.remove("hidden");
            dashboardViewEl.classList.add("hidden");
        } else {
            welcomeViewEl.classList.add("hidden");
            dashboardViewEl.classList.remove("hidden");
        }
    } else {
        navBtnExplorer.classList.remove("active");
        navBtnStats.classList.add("active");
        
        welcomeViewEl.classList.add("hidden");
        dashboardViewEl.classList.add("hidden");
        globalStatsViewEl.classList.remove("hidden");
        
        loadGlobalStats();
    }
    
    lucide.createIcons();
}

// Global Stats & Comparison Table
async function loadGlobalStats() {
    try {
        const resp = await fetch("/api/global-status");
        if (!resp.ok) throw new Error("Error loading global stats");
        globalStatsData = await resp.json();
        
        const families = Object.keys(globalStatsData);
        const scannedCount = families.filter(f => globalStatsData[f].scanned).length;
        
        let totalCommons = 0;
        let totalLocal = 0;
        
        families.forEach(f => {
            totalCommons += globalStatsData[f].commons_files;
            totalLocal += globalStatsData[f].local_files;
        });
        
        globalScannedCountEl.textContent = `${scannedCount} / ${families.length}`;
        globalCommonsFilesEl.textContent = totalCommons.toLocaleString();
        globalLocalFilesEl.textContent = totalLocal.toLocaleString();
        
        renderStatsTable();
    } catch (e) {
        console.error("Error loading global stats:", e);
        statsTableBodyEl.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 40px;">Error: ${e.message}</td></tr>`;
    }
}

function renderStatsTable() {
    const query = statsTableSearchEl.value.toLowerCase().trim();
    const families = Object.keys(globalStatsData).sort();
    
    const filtered = families.filter(name => name.toLowerCase().includes(query));
    
    if (filtered.length === 0) {
        statsTableBodyEl.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 40px;">No se encontraron familias.</td></tr>`;
        return;
    }
    
    statsTableBodyEl.innerHTML = filtered.map(name => {
        const info = globalStatsData[name];
        let badgeClass = "unscanned";
        let badgeText = "Sin Escanear";
        
        if (info.scanned) {
            if (info.progress >= 100.0 && info.commons_files > 0) {
                badgeClass = "completed";
                badgeText = "Completado";
            } else {
                badgeClass = "pending";
                badgeText = "Pendiente";
            }
        }
        
        const dateStr = info.last_scan ? info.last_scan : "-";
        
        return `
            <tr style="height: 50px; border-bottom: 1px solid rgba(255, 255, 255, 0.02);">
                <td style="font-weight: 500;">${name}</td>
                <td>${info.commons_files}</td>
                <td>${info.local_files}</td>
                <td>
                    <div class="progress-bar-container">
                        <div class="progress-bar-bg">
                            <div class="progress-bar-fill" style="width: ${info.progress}%;"></div>
                        </div>
                        <span style="font-size: 11px; width: 35px; text-align: right; display: inline-block;">${info.progress}%</span>
                    </div>
                </td>
                <td style="color: var(--text-muted);">${dateStr}</td>
                <td>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <span class="status-badge ${badgeClass}">${badgeText}</span>
                        <button class="btn btn-outline" style="padding: 4px 8px; font-size: 11px;" onclick="quickJumpToFamily('${name}')">
                            <i data-lucide="eye" style="width: 12px; height: 12px;"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
    
    lucide.createIcons();
}

function filterStatsTable() {
    renderStatsTable();
}

window.quickJumpToFamily = function(familyName) {
    switchTab("explorer");
    selectFamily(familyName);
};

// Batch Scan Controls
async function startBatchScan() {
    btnBatchScanEl.disabled = true;
    const depth = parseInt(batchScanDepthEl.value);
    
    try {
        const resp = await fetch("/api/batch-scan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ depth: depth })
        });
        if (!resp.ok) throw new Error("Error initiating batch scan");
        const data = await resp.json();
        
        if (data.status === "started") {
            addTerminalLine("[SISTEMA] Iniciando escaneo por lotes Pywikibot en segundo plano...", "system");
        }
    } catch (e) {
        addTerminalLine(`[SISTEMA ERROR] No se pudo iniciar el lote: ${e.message}`, "error");
        btnBatchScanEl.disabled = false;
    }
}

async function stopBatchScan() {
    btnBatchStopEl.disabled = true;
    try {
        const resp = await fetch("/api/batch-scan/stop", { method: "POST" });
        if (!resp.ok) throw new Error("Error stopping batch scan");
    } catch (e) {
        addTerminalLine(`[SISTEMA ERROR] No se pudo parar el lote: ${e.message}`, "error");
        btnBatchStopEl.disabled = false;
    }
}

// Wikipedia Article Controller (Callable from internal iframe links)
window.downloadWikipediaArticle = async function(customQuery = null) {
    if (!activeFamily && !customQuery) return;
    
    let query = activeFamily;
    if (typeof customQuery === "string" && customQuery.trim()) {
        query = customQuery.trim();
    }
    
    btnWikiDownloadEl.disabled = true;
    btnWikiDownloadEl.innerHTML = `<i data-lucide="loader" class="logo-icon spin small-icon"></i> <span>Descargando...</span>`;
    lucide.createIcons();
    
    addTerminalLine(`[SISTEMA] Solicitando artículo de Wikipedia para '${query}'...`, "system");
    
    try {
        const resp = await fetch(`/api/wikipedia/${activeFamily || query}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: query })
        });
        
        if (!resp.ok) {
            const errData = await resp.json();
            throw new Error(errData.error || "Error de red");
        }
        
        const data = await resp.json();
        addTerminalLine(`[SISTEMA] ¡Artículo de Wikipedia cargado para '${query}'!`, "ok");
        
        wikiQueryInputEl.style.display = "none";
        await refreshActiveFamilyDetails();
    } catch (e) {
        addTerminalLine(`[SISTEMA ERROR] Wikipedia falló: ${e.message}`, "error");
        btnWikiDownloadEl.disabled = false;
        btnWikiDownloadEl.innerHTML = `<i data-lucide="download" class="small-icon"></i> <span>Descargar Artículo</span>`;
        lucide.createIcons();
    }
}

function toggleWikiCustomSearch() {
    if (wikiQueryInputEl.style.display === "none") {
        wikiQueryInputEl.style.display = "inline-block";
        wikiQueryInputEl.focus();
    } else {
        wikiQueryInputEl.style.display = "none";
    }
}

// Sublinks & Hash URL Routing (e.g., /#album?asteraceae%familia or /#explorer?family=Asteraceae)
function parseUrlHash() {
    const hash = window.location.hash;
    if (!hash) return;
    
    let tab = "explorer";
    let family = null;
    
    if (hash.startsWith("#stats")) {
        tab = "stats";
    } else if (hash.startsWith("#album") || hash.startsWith("#explorer")) {
        tab = "explorer";
        const queryIndex = hash.indexOf("?");
        if (queryIndex !== -1) {
            const queryStr = decodeURIComponent(hash.substring(queryIndex + 1));
            const params = new URLSearchParams(queryStr);
            family = params.get("family");
            if (!family) {
                // Support format like #album?asteraceae%familia or #album?asteraceae
                const parts = queryStr.split(/[%&]/);
                if (parts[0]) {
                    family = parts[0].capitalize();
                }
            }
        }
    }
    
    switchTab(tab);
    if (family && familiesData.some(f => f.name.toLowerCase() === family.toLowerCase())) {
        const matched = familiesData.find(f => f.name.toLowerCase() === family.toLowerCase()).name;
        if (activeFamily !== matched) {
            selectFamily(matched);
        }
    }
}

function updateUrlHash() {
    if (activeTab === "stats") {
        window.history.replaceState(null, "", "#stats");
    } else if (activeFamily) {
        window.history.replaceState(null, "", `/#album?family=${encodeURIComponent(activeFamily)}`);
    } else {
        window.history.replaceState(null, "", "#explorer");
    }
}

// Helpers
String.prototype.capitalize = function() {
    return this.charAt(0).toUpperCase() + this.slice(1);
};

function sanitizeFilenameForJS(title) {
    if (title.toLowerCase().indexOf("file:") === 0) {
        title = title.substring(5);
    }
    let sanitized = title.replace(/[\\/*?:"<>|]/g, "_");
    sanitized = sanitized.replace(/ /g, "_");
    sanitized = sanitized.replace(/_{2,}/g, "_");
    if (sanitized.indexOf('_') === 0) sanitized = sanitized.substring(1);
    if (sanitized.lastIndexOf('_') === sanitized.length - 1) sanitized = sanitized.substring(0, sanitized.length - 1);
    return sanitized;
}
