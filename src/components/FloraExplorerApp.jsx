import { useState, useEffect, useRef } from 'preact/hooks';

// String capitalization helper
const capitalize = (str) => {
    if (!str) return "";
    return str.charAt(0).toUpperCase() + str.slice(1);
};

// Redefine sanitize logic in JS to match python sanitization
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

const AlbumIcon = ({ name, size = 16, filled = false, className = '' }) => {
    const props = {
        width: size,
        height: size,
        viewBox: '0 0 24 24',
        fill: filled ? 'currentColor' : 'none',
        stroke: 'currentColor',
        strokeWidth: 2,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        className,
    };

    if (name === 'star') {
        return (
            <svg {...props}>
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
            </svg>
        );
    }
    if (name === 'edit-2') {
        return (
            <svg {...props}>
                <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
                <path d="m15 5 4 4" />
            </svg>
        );
    }
    if (name === 'trash-2') {
        return (
            <svg {...props}>
                <path d="M3 6h18" />
                <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
                <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
                <line x1="10" x2="10" y1="11" y2="17" />
                <line x1="14" x2="14" y1="11" y2="17" />
            </svg>
        );
    }
    if (name === 'image-off') {
        return (
            <svg {...props}>
                <line x1="2" x2="22" y1="2" y2="22" />
                <path d="M10.41 10.41a2 2 0 1 1-2.83-2.83" />
                <line x1="13.5" x2="6" y1="13.5" y2="21" />
                <line x1="18" x2="21" y1="12" y2="15" />
                <path d="M3.59 3.59A1.99 1.99 0 0 0 3 5v14a2 2 0 0 0 2 2h14c.55 0 1.052-.22 1.41-.59" />
                <path d="M21 15V5a2 2 0 0 0-2-2H9" />
            </svg>
        );
    }
    return null;
};

const Spinner = ({ size = 24, className = '', style = undefined }) => (
    <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        className={className}
        style={style}
        aria-hidden="true"
    >
        <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
);

const APP_TABS = ['explorer', 'album', 'stats'];

function parseHash() {
    const raw = window.location.hash.replace(/^#\/?/, '');
    if (!raw) return { tab: 'explorer', family: null, genus: null };
    
    const [slugPart, queryPart] = raw.split('?');
    let tab = 'explorer';
    if (slugPart === 'album' || slugPart === 'stats') {
        tab = slugPart;
    }
    
    let family = null;
    let genus = null;
    if (queryPart) {
        const decoded = decodeURIComponent(queryPart);
        const params = new URLSearchParams(decoded);
        family = params.get('family');
        genus = params.get('genus');
        if (!family) {
            const firstWord = decoded.split(/[%&]/)[0];
            if (firstWord && firstWord !== 'familia') family = capitalize(firstWord);
        }
    }
    return { tab, family, genus };
}

function updateHash(tab, family, genus) {
    let newHash = tab === 'explorer' ? '#/' : `#/${tab}`;
    if (family) {
        newHash += `?family=${encodeURIComponent(family)}`;
        if (genus) newHash += `&genus=${encodeURIComponent(genus)}`;
    }
    if (window.location.hash !== newHash) {
        window.history.replaceState(null, '', newHash);
    }
}

// Recursive Tree Node Component with expand/collapse control
const TreeNode = ({ node, forceExpanded }) => {
    const [collapsed, setCollapsed] = useState(false);

    useEffect(() => {
        if (forceExpanded !== undefined && forceExpanded !== null) {
            setCollapsed(!forceExpanded);
        }
    }, [forceExpanded]);
    
    if (!node) return null;
    
    const hasChildren = node.children && node.children.length > 0;
    const hasFiles = node.files_count > 0;
    const depthLevel = node.depth ? `L${node.depth}` : null;
    
    let infoText = "";
    if (hasFiles && hasChildren) {
        infoText = `${node.files_count} F, ${node.children.length} C`;
    } else if (hasFiles) {
        infoText = `${node.files_count} F`;
    } else if (hasChildren) {
        infoText = `${node.children.length} C`;
    } else {
        infoText = "empty";
    }
    
    return (
        <div className="tree-node" style={{ margin: '3px 0' }}>
            <div className="tree-node-header" onClick={() => hasChildren && setCollapsed(!collapsed)} style={{ cursor: hasChildren ? 'pointer' : 'default', userSelect: 'none', display: 'flex', alignItems: 'center' }}>
                {hasChildren ? (
                    <span className="tree-node-toggle" style={{ width: '16px', display: 'inline-block' }}>
                        <i data-lucide={collapsed ? "chevron-right" : "chevron-down"} className="tree-node-toggle-icon small-icon"></i>
                    </span>
                ) : (
                    <span style={{ width: '16px', display: 'inline-block' }}></span>
                )}
                <i data-lucide="folder" className="tree-node-icon small-icon" style={{ marginRight: '6px', color: 'var(--accent)' }}></i>
                <span className="tree-node-name" style={{ fontWeight: 500, marginRight: '8px' }}>{node.name}</span>
                {depthLevel && (
                    <span style={{ fontSize: '10px', fontWeight: 600, padding: '1px 5px', borderRadius: '3px', backgroundColor: node.depth === 1 ? 'rgba(59, 130, 246, 0.2)' : (node.depth === 2 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(168, 85, 247, 0.2)'), color: node.depth === 1 ? '#60a5fa' : (node.depth === 2 ? '#34d399' : '#c084fc'), marginRight: '6px' }}>
                        {depthLevel}
                    </span>
                )}
                <span className="tree-node-badge" style={{ fontSize: '11px', opacity: 0.7 }}>({infoText})</span>
            </div>
            {hasChildren && !collapsed && (
                <ul className="tree-node-children" style={{ listStyle: 'none', margin: '4px 0 4px 6px', paddingLeft: '14px', borderLeft: '1px dashed rgba(255,255,255,0.15)' }}>
                    {node.children.map((child, idx) => (
                        <li key={idx} style={{ listStyle: 'none' }}>
                            <TreeNode node={child} forceExpanded={forceExpanded} />
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
};

// Collapsible genus section used in the family gallery
const CollapsibleGenus = ({ id, label, badge, color, bgColor, borderColor, count, defaultOpen = true, forceOpen, children }) => {
    const storageKey = `genus-open:${id}`;
    const stored = sessionStorage.getItem(storageKey);
    const [open, setOpen] = useState(stored !== null ? stored === '1' : defaultOpen);

    // External override: when forceOpen changes, sync internal state
    useEffect(() => {
        if (forceOpen !== undefined && forceOpen !== null) {
            setOpen(forceOpen);
            sessionStorage.setItem(storageKey, forceOpen ? '1' : '0');
        }
    }, [forceOpen]);

    const toggle = () => {
        const next = !open;
        setOpen(next);
        sessionStorage.setItem(storageKey, next ? '1' : '0');
    };

    return (
        <div style={{ marginBottom: '32px' }}>
            <div style={{
                display: 'flex', alignItems: 'center', gap: '10px',
                marginBottom: open ? '12px' : '0',
                paddingBottom: '8px',
                borderBottom: '1px solid rgba(255,255,255,0.06)',
                userSelect: 'none',
            }}>
                <span style={{
                    fontSize: '11px', fontWeight: 700, letterSpacing: '0.08em',
                    textTransform: 'uppercase', color,
                    padding: '3px 8px', borderRadius: '4px',
                    background: bgColor, border: `1px solid ${borderColor}`
                }}>{label}</span>
                {badge && <h4 style={{ margin: 0, fontSize: '15px', color: '#fff', fontStyle: 'italic' }}>{badge}</h4>}
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>({count})</span>

                {/* Spacer */}
                <span style={{ flex: 1 }} />

                {/* +/- toggle button */}
                <button
                    onClick={toggle}
                    title={open ? 'Colapsar' : 'Expandir'}
                    style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        width: '22px', height: '22px',
                        borderRadius: '5px',
                        border: `1px solid ${borderColor}`,
                        background: bgColor,
                        color,
                        fontSize: '16px', fontWeight: 700, lineHeight: 1,
                        cursor: 'pointer',
                        flexShrink: 0,
                        transition: 'background 0.15s, transform 0.1s',
                        padding: 0,
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = borderColor; }}
                    onMouseLeave={e => { e.currentTarget.style.background = bgColor; }}
                    onMouseDown={e => { e.currentTarget.style.transform = 'scale(0.88)'; }}
                    onMouseUp={e => { e.currentTarget.style.transform = 'scale(1)'; }}
                >
                    {open ? '−' : '+'}
                </button>
            </div>

            <div style={{
                overflow: 'hidden',
                maxHeight: open ? '99999px' : '0',
                opacity: open ? 1 : 0,
                transition: open
                    ? 'max-height 0.35s ease, opacity 0.2s ease'
                    : 'max-height 0.25s ease, opacity 0.15s ease',
            }}>
                {children}
            </div>
        </div>
    );
};

// Lightbox Modal Component with Zoom, Pan, PDF Viewer & AI Classification
function LightboxModal({ lightbox, onClose, onNavigate, onToggleFav, filteredItems, API_BASE, activeFamily }) {
    if (!lightbox) return null;

    const [zoomLevel, setZoomLevel] = useState(1.0);
    const [translateX, setTranslateX] = useState(0);
    const [translateY, setTranslateY] = useState(0);
    const [isDragging, setIsDragging] = useState(false);
    const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

    const [aiResult, setAiResult] = useState(null);
    const [aiLoading, setAiLoading] = useState(false);

    // Reset zoom, pan and AI result whenever the displayed image changes
    useEffect(() => {
        setZoomLevel(1.0);
        setTranslateX(0);
        setTranslateY(0);
        setAiResult(null);
        setAiLoading(false);
    }, [lightbox.src]);


    const isPdf = lightbox.src.toLowerCase().endsWith('.pdf') || (lightbox.title && lightbox.title.toLowerCase().endsWith('.pdf'));

    const handleResetZoom = () => {
        setZoomLevel(1.0);
        setTranslateX(0);
        setTranslateY(0);
    };

    const handleZoomIn = () => setZoomLevel(prev => Math.min(prev + 0.25, 4.0));
    const handleZoomOut = () => {
        setZoomLevel(prev => {
            const next = Math.max(prev - 0.25, 0.5);
            if (next <= 1.0) { setTranslateX(0); setTranslateY(0); }
            return next;
        });
    };

    const handleWheel = (e) => {
        if (isPdf) return;
        e.preventDefault();
        if (e.deltaY < 0) {
            setZoomLevel(prev => Math.min(prev + 0.15, 4.0));
        } else {
            setZoomLevel(prev => {
                const next = Math.max(prev - 0.15, 0.5);
                if (next <= 1.0) { setTranslateX(0); setTranslateY(0); }
                return next;
            });
        }
    };

    const handleMouseDown = (e) => {
        if (zoomLevel <= 1.0 || isPdf) return;
        e.preventDefault();
        setIsDragging(true);
        setDragStart({ x: e.clientX - translateX, y: e.clientY - translateY });
    };

    const handleMouseMove = (e) => {
        if (!isDragging) return;
        e.preventDefault();
        setTranslateX(e.clientX - dragStart.x);
        setTranslateY(e.clientY - dragStart.y);
    };

    const handleMouseUp = () => setIsDragging(false);

    // AI Classification Handler
    const triggerAi = async () => {
        const itemFamily = lightbox.family || activeFamily;
        let filename = lightbox.filename;
        if (!filename && lightbox.title) {
            let base = sanitizeFilenameForJS(lightbox.title);
            let ext = lightbox.title.lastIndexOf('.') !== -1 ? lightbox.title.substring(lightbox.title.lastIndexOf('.')) : ".jpg";
            filename = base + ext;
        }
        if (!itemFamily || !filename) return;

        setAiLoading(true);
        try {
            const resp = await fetch(`${API_BASE}/api/ai-classify`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ family: itemFamily, filename: filename })
            });
            if (!resp.ok) throw new Error("Error en Gemini IA");
            const data = await resp.json();
            setAiResult(data.result);
        } catch (e) {
            alert("Error Gemini IA: " + e.message);
        } finally {
            setAiLoading(false);
        }
    };

    const currentItem = (lightbox.albumIndex !== undefined && filteredItems) ? filteredItems[lightbox.albumIndex] : null;

    return (
        <div className="modal" id="image-modal" style={{ display: 'flex', zIndex: 9999 }}>
            <div className="modal-overlay" onClick={onClose}></div>
            <div className="modal-content-wrapper" style={{ maxWidth: '920px', width: '94%', position: 'relative' }}>
                <button className="modal-close" onClick={onClose}>
                    <i data-lucide="x"></i>
                </button>

                {lightbox.albumIndex !== undefined && (
                    <>
                        <button className="lightbox-nav-btn prev" onClick={(e) => { e.stopPropagation(); onNavigate(-1); }} style={{ position: 'absolute', left: '-50px', top: '50%', transform: 'translateY(-50%)', background: 'rgba(0,0,0,0.6)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '50%', width: '40px', height: '40px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', cursor: 'pointer', zIndex: 100 }}>
                            <i data-lucide="chevron-left" style={{ width: '20px', height: '20px' }}></i>
                        </button>
                        <button className="lightbox-nav-btn next" onClick={(e) => { e.stopPropagation(); onNavigate(1); }} style={{ position: 'absolute', right: '-50px', top: '50%', transform: 'translateY(-50%)', background: 'rgba(0,0,0,0.6)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '50%', width: '40px', height: '40px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', cursor: 'pointer', zIndex: 100 }}>
                            <i data-lucide="chevron-right" style={{ width: '20px', height: '20px' }}></i>
                        </button>
                    </>
                )}

                <div className="modal-body" style={{ padding: '20px' }}>
                    <div 
                        className="modal-view-container" 
                        onWheel={handleWheel}
                        onMouseDown={handleMouseDown}
                        onMouseMove={handleMouseMove}
                        onMouseUp={handleMouseUp}
                        onMouseLeave={handleMouseUp}
                        style={{ position: 'relative', overflow: 'hidden', background: '#05080e', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '400px', maxHeight: '68vh' }}
                    >
                        {isPdf ? (
                            <iframe src={lightbox.src} style={{ width: '100%', height: '550px', border: 0, background: '#ffffff' }}></iframe>
                        ) : (
                            <img 
                                src={lightbox.src} 
                                alt={lightbox.title} 
                                draggable="false"
                                onDragStart={(e) => e.preventDefault()}
                                style={{ 
                                    maxWidth: '100%', 
                                    maxHeight: '68vh', 
                                    transform: `translate(${translateX}px, ${translateY}px) scale(${zoomLevel})`,
                                    transition: isDragging ? 'none' : 'transform 0.1s ease-out',
                                    cursor: zoomLevel > 1.0 ? (isDragging ? 'grabbing' : 'grab') : 'default',
                                    userSelect: 'none',
                                    WebkitUserDrag: 'none',
                                    WebkitUserSelect: 'none',
                                    pointerEvents: zoomLevel > 1.0 ? 'auto' : 'auto'
                                }}
                            />
                        )}

                        {!isPdf && (
                            <div className="modal-zoom-controls" style={{ position: 'absolute', bottom: '16px', right: '16px', display: 'flex', gap: '6px', background: 'rgba(11, 15, 25, 0.85)', backdropFilter: 'blur(8px)', padding: '6px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', zIndex: 10 }}>
                                <button className="btn btn-outline" style={{ padding: '6px' }} onClick={handleZoomIn} title="Acercar (+)">
                                    <i data-lucide="zoom-in" className="small-icon"></i>
                                </button>
                                <button className="btn btn-outline" style={{ padding: '6px' }} onClick={handleZoomOut} title="Alejar (-)">
                                    <i data-lucide="zoom-out" className="small-icon"></i>
                                </button>
                                <button className="btn btn-outline" style={{ padding: '6px' }} onClick={handleResetZoom} title="Restablecer Zoom">
                                    <i data-lucide="rotate-ccw" className="small-icon"></i>
                                </button>
                                <span style={{ fontSize: '11px', color: '#a0aec0', display: 'flex', alignItems: 'center', padding: '0 6px' }}>{Math.round(zoomLevel * 100)}%</span>
                            </div>
                        )}
                    </div>

                    <div className="modal-info" style={{ marginTop: '16px', padding: '16px 0 0 0' }}>
                        <h4 style={{ margin: '0 0 12px 0', fontSize: '16px', color: '#fff' }}>{lightbox.title.replace("File:", "")}</h4>

                        {aiResult && (
                            <div className="modal-ai-box" style={{ marginBottom: '16px', padding: '12px', background: 'rgba(139, 92, 246, 0.12)', border: '1px solid rgba(139, 92, 246, 0.3)', borderRadius: '8px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px', color: '#a78bfa', fontWeight: 600, fontSize: '12px' }}>
                                    <i data-lucide="sparkles" className="small-icon"></i>
                                    <span>Análisis Inteligente Gemini IA</span>
                                </div>
                                <div style={{ display: 'flex', gap: '8px', marginBottom: '6px' }}>
                                    <span className="ai-badge">Órgano: {aiResult.organ || 'No especificado'}</span>
                                    <span className="ai-badge" style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', borderColor: 'rgba(16, 185, 129, 0.3)' }}>Estilo: {aiResult.style || 'Ilustración'}</span>
                                </div>
                                <p style={{ margin: '4px 0 8px 0', color: '#cbd5e1', fontSize: '13px' }}>{aiResult.description || ''}</p>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                                    {aiResult.tags && aiResult.tags.map((t, idx) => (
                                        <span key={idx} className="ai-tag-pill">{t}</span>
                                    ))}
                                </div>
                            </div>
                        )}

                        <div className="modal-actions-row" style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
                            {currentItem && (
                                <button className="btn btn-outline" onClick={() => onToggleFav(currentItem)} style={{ color: currentItem.favorite ? 'var(--accent)' : 'inherit', borderColor: currentItem.favorite ? 'var(--accent)' : 'inherit' }}>
                                    <i data-lucide="star" style={{ fill: currentItem.favorite ? 'currentColor' : 'none', width: '14px', height: '14px' }}></i>
                                    <span>{currentItem.favorite ? "Favorito" : "Marcar Favorito"}</span>
                                </button>
                            )}
                            {lightbox.commonsUrl && (
                                <a href={lightbox.commonsUrl} target="_blank" className="btn btn-outline">
                                    <i data-lucide="external-link" className="small-icon"></i>
                                    <span>Ver en Commons</span>
                                </a>
                            )}
                            <a href={lightbox.src} target="_blank" className="btn btn-primary">
                                <i data-lucide="maximize-2" className="small-icon"></i>
                                <span>Máxima Resolución Original</span>
                            </a>
                            <button className="btn btn-accent" onClick={triggerAi} disabled={aiLoading} style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)', color: 'white', border: 0 }}>
                                <i data-lucide="sparkles" className="small-icon"></i>
                                <span>{aiLoading ? "Analizando IA..." : "Categorizar con IA"}</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

export default function FloraExplorerApp() {
    const [activeTab, setActiveTab] = useState('explorer');
    const [activeFamily, setActiveFamily] = useState(null);
    const [familiesData, setFamiliesData] = useState([]);
    const [familySearch, setFamilySearch] = useState("");
    const [pinnedFamilies, setPinnedFamilies] = useState(() => {
        try { return JSON.parse(localStorage.getItem('pinned_families') || '[]'); } catch { return []; }
    });

    const [activeFamilyDetails, setActiveFamilyDetails] = useState({
        scanned: false,
        files: [],
        tree: null,
        wikipedia_url: null,
        path: ""
    });

    const [treeExpandedAll, setTreeExpandedAll] = useState(undefined);
    const [treePanelExpanded, setTreePanelExpanded] = useState(false);
    const [wikiPanelExpanded, setWikiPanelExpanded] = useState(false);

    const [logs, setLogs] = useState([]);
    const [activeScans, setActiveScans] = useState({});
    const [activeTasks, setActiveTasks] = useState({});
    const [batchScan, setBatchScan] = useState({
        active: false,
        current_family: "",
        processed: 0,
        total: 0
    });

    const [globalStats, setGlobalStats] = useState({});
    const [statsSearch, setStatsSearch] = useState("");

    const [scanDepth, setScanDepth] = useState(3);
    const [batchScanDepth, setBatchScanDepth] = useState(3);

    const [wikiQuery, setWikiQuery] = useState("");
    const [wikiCustomSearchVisible, setWikiCustomSearchVisible] = useState(false);
    const [wikiLoading, setWikiLoading] = useState(false);

    const [lightbox, setLightbox] = useState(null);

    // Album State
    const [albumItems, setAlbumItems] = useState([]);
    const [albumSearch, setAlbumSearch] = useState("");
    const [albumFamilyFilter, setAlbumFamilyFilter] = useState("all");
    const [albumLevelFilter, setAlbumLevelFilter] = useState("all");
    const [albumOnlyFavorites, setAlbumOnlyFavorites] = useState(false);
    const [albumLoading, setAlbumLoading] = useState(false);
    const [renamingItem, setRenamingItem] = useState(null);

    const lastLogIdRef = useRef(0);
    const terminalRef = useRef(null);
    const lucideTimerRef = useRef(null);
    const albumLoadGenRef = useRef(0);

    const API_BASE = "http://localhost:5000";

    const triggerLucide = () => {
        if (lucideTimerRef.current) clearTimeout(lucideTimerRef.current);
        lucideTimerRef.current = setTimeout(() => {
            lucideTimerRef.current = null;
            if (!window.lucide) return;
            const root = document.querySelector('.app-container');
            window.lucide.createIcons(root ? { root } : undefined);
        }, 80);
    };

    const sameSnapshot = (a, b) => JSON.stringify(a) === JSON.stringify(b);

    function applyStateFromHash() {
        const parsed = parseHash();
        setActiveTab(parsed.tab);
        if (parsed.tab === 'album') loadAlbum();
        if (parsed.family) {
            setAlbumFamilyFilter(parsed.family);
            if (activeFamily !== parsed.family) {
                selectFamily(parsed.family, false);
            }
        }
    }

    function navigateToTab(tab) {
        if (!APP_TABS.includes(tab)) return;
        setActiveTab(tab);
        if (tab === 'album') loadAlbum();
        updateHash(tab, activeFamily);
    }

    // Sync tab and parameters with URL hash
    useEffect(() => {
        applyStateFromHash();
        const onHashChange = () => applyStateFromHash();
        window.addEventListener('hashchange', onHashChange);
        return () => window.removeEventListener('hashchange', onHashChange);
    }, []);

    // Wikipedia postMessage Listener (captures clicks inside Wikipedia iframe cleanly)
    useEffect(() => {
        const handleMessage = (e) => {
            if (e.data && e.data.type === 'WIKI_NAVIGATE' && e.data.term) {
                downloadWikipediaArticle(e.data.term);
            }
        };
        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, [activeFamily]);

    // Load initial families & stats
    useEffect(() => {
        loadFamilies();
        loadGlobalStats();

        let isBusy = false;
        const fetchStatus = async () => {
            try {
                const resp = await fetch(`${API_BASE}/api/status?since_id=${lastLogIdRef.current}`);
                if (!resp.ok) return;
                const data = await resp.json();

                const nextScans = data.scans || {};
                setActiveScans(prev => sameSnapshot(prev, nextScans) ? prev : nextScans);

                const taskMap = {};
                if (data.tasks) {
                    data.tasks.forEach(t => { taskMap[t.family] = t; });
                }
                setActiveTasks(prev => sameSnapshot(prev, taskMap) ? prev : taskMap);

                // Update logs with incremental IDs
                if (data.logs && data.logs.length > 0) {
                    data.logs.forEach(item => {
                        const text = item.text || item;
                        setLogs(prev => [...prev, text]);
                        if (item.id && item.id > lastLogIdRef.current) {
                            lastLogIdRef.current = item.id;
                        }
                    });

                    setTimeout(() => {
                        if (terminalRef.current) {
                            terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
                        }
                    }, 50);
                }

                if (data.batch_scan) {
                    setBatchScan(prev => sameSnapshot(prev, data.batch_scan) ? prev : data.batch_scan);
                    if (data.batch_scan.active && activeTab === "stats" && Math.random() < 0.25) {
                        loadGlobalStats();
                    }
                }

                // Check if any activity is running
                const hasRunningTask = Object.values(taskMap).some(t => t.status === "running");
                const hasRunningScan = Object.values(nextScans).some(s => s.status === "running");
                isBusy = hasRunningTask || hasRunningScan || (data.batch_scan && data.batch_scan.active);
            } catch (e) {
                console.error("Error polling status:", e);
            }
        };

        let timerId = null;
        const schedulePoll = () => {
            timerId = setTimeout(async () => {
                await fetchStatus();
                schedulePoll();
            }, isBusy ? 1000 : 2500);
        };
        schedulePoll();

        return () => clearTimeout(timerId);
    }, []);

    // Load global status whenever entering stats tab
    useEffect(() => {
        if (activeTab === "stats") {
            loadGlobalStats();
        }
    }, [activeTab]);

    async function loadFamilies() {
        try {
            const resp = await fetch(`${API_BASE}/api/families`);
            if (!resp.ok) throw new Error("Error loading families");
            const data = await resp.json();
            setFamiliesData(data);
        } catch (e) {
            console.error(e);
        }
    }

    async function loadGlobalStats() {
        try {
            const resp = await fetch(`${API_BASE}/api/global-status`);
            if (!resp.ok) throw new Error("Error loading global stats");
            const data = await resp.json();
            setGlobalStats(data);
        } catch (e) {
            console.error("Error loading global stats:", e);
        }
    }

    function togglePinFamily(name, e) {
        e.stopPropagation();
        const next = pinnedFamilies.includes(name) 
            ? pinnedFamilies.filter(x => x !== name) 
            : [...pinnedFamilies, name];
        setPinnedFamilies(next);
        localStorage.setItem('pinned_families', JSON.stringify(next));
    }

    async function selectFamily(name, updateUrl = true) {
        setActiveFamily(name);
        if (updateUrl) {
            updateHash(activeTab, name);
        }

        const familyInfo = familiesData.find(f => f.name === name);
        const path = familyInfo ? familyInfo.path : "";

        setActiveFamilyDetails({
            scanned: false,
            files: [],
            tree: null,
            wikipedia_url: null,
            path: path
        });

        setWikiQuery("");
        setWikiCustomSearchVisible(false);

        await refreshActiveFamilyDetails(name);
    }

    async function refreshActiveFamilyDetails(name) {
        if (!name) return;
        try {
            const resp = await fetch(`${API_BASE}/api/files/${name}`);
            const data = await resp.json();

            const familyInfo = familiesData.find(f => f.name === name);
            const path = familyInfo ? familyInfo.path : "";

            const wikiUrl = data.wikipedia_url ? `${data.wikipedia_url}?t=${Date.now()}` : null;

            if (data.scanned) {
                setActiveFamilyDetails({
                    scanned: true,
                    files: data.files || [],
                    tree: data.tree || null,
                    wikipedia_url: wikiUrl,
                    path: path
                });
            } else {
                setActiveFamilyDetails({
                    scanned: false,
                    files: [],
                    tree: null,
                    wikipedia_url: wikiUrl,
                    path: path
                });
            }
        } catch (e) {
            console.error("Error refreshing family details:", e);
        }
    }

    async function scanActiveFamily() {
        if (!activeFamily) return;
        try {
            const resp = await fetch(`${API_BASE}/api/scan/${activeFamily}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ depth: scanDepth })
            });
            if (!resp.ok) throw new Error("Error initiating scan");
        } catch (e) {
            addLocalLogLine(`[SISTEMA ERROR] No se pudo iniciar el escaneo: ${e.message}`, "error");
        }
    }

    async function startDownloadActiveFamily() {
        if (!activeFamily) return;
        try {
            const resp = await fetch(`${API_BASE}/api/download/${activeFamily}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ threads: 2 })
            });
            if (!resp.ok) throw new Error("Error initiating download");
        } catch (e) {
            addLocalLogLine(`[SISTEMA ERROR] No se pudo iniciar la descarga: ${e.message}`, "error");
        }
    }

    async function pauseDownloadActiveFamily() {
        if (!activeFamily) return;
        try {
            const resp = await fetch(`${API_BASE}/api/pause/${activeFamily}`, { method: "POST" });
            if (!resp.ok) throw new Error("Error pausing downloads");
        } catch (e) {
            addLocalLogLine(`[SISTEMA ERROR] No se pudo pausar la descarga: ${e.message}`, "error");
        }
    }

    async function startBatchScan() {
        try {
            const resp = await fetch(`${API_BASE}/api/batch-scan`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ depth: batchScanDepth })
            });
            if (!resp.ok) throw new Error("Error initiating batch scan");
        } catch (e) {
            addLocalLogLine(`[SISTEMA ERROR] No se pudo iniciar el lote: ${e.message}`, "error");
        }
    }

    async function stopBatchScan() {
        try {
            const resp = await fetch(`${API_BASE}/api/batch-scan/stop`, { method: "POST" });
            if (!resp.ok) throw new Error("Error stopping batch scan");
        } catch (e) {
            addLocalLogLine(`[SISTEMA ERROR] No se pudo detener el lote: ${e.message}`, "error");
        }
    }

    async function downloadWikipediaArticle(customQuery = null) {
        if (!activeFamily && !customQuery) return;

        let query = activeFamily;
        if (typeof customQuery === "string" && customQuery.trim()) {
            query = customQuery.trim();
        }

        setWikiLoading(true);
        addLocalLogLine(`[SISTEMA] Solicitando artículo de Wikipedia para '${query}'...`, "system");

        try {
            const resp = await fetch(`${API_BASE}/api/wikipedia/${activeFamily || query}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query: query })
            });

            if (!resp.ok) {
                const errData = await resp.json();
                throw new Error(errData.error || "Error de red");
            }

            const wikiData = await resp.json();
            addLocalLogLine(`[SISTEMA] ¡Artículo de Wikipedia cargado para '${query}'!`, "ok");
            setWikiCustomSearchVisible(false);

            const newWikiUrl = wikiData.article_url ? `${wikiData.article_url}?t=${Date.now()}` : null;
            setActiveFamilyDetails(prev => ({
                ...prev,
                wikipedia_url: newWikiUrl
            }));
        } catch (e) {
            addLocalLogLine(`[SISTEMA ERROR] Wikipedia falló: ${e.message}`, "error");
        } finally {
            setWikiLoading(false);
        }
    }

    function addLocalLogLine(text, style = "system") {
        const formatted = `[${new Date().toLocaleTimeString()}] ${text}`;
        setLogs(prev => [...prev, formatted]);
    }

    function quickJumpToFamily(familyName) {
        navigateToTab("explorer");
        selectFamily(familyName);

        setTimeout(() => {
            const spanEl = Array.from(document.querySelectorAll('.family-name')).find(el => el.textContent === familyName);
            if (spanEl) {
                spanEl.closest('li').scrollIntoView({ block: 'center', behavior: 'smooth' });
            }
        }, 150);
    }

    const activeFamilyCap = activeFamily ? capitalize(activeFamily) : null;
    const currentScan = activeFamilyCap ? activeScans[activeFamilyCap] : null;
    const currentTask = activeFamilyCap ? activeTasks[activeFamilyCap] : null;

    useEffect(() => {
        triggerLucide();
    }, [
        activeTab,
        activeFamily,
        activeFamilyDetails,
        currentScan?.status,
        currentTask?.status,
        batchScan.active,
        pinnedFamilies
    ]);

    const audioCtxRef = useRef(null);
    const prevScanStatusRef = useRef(null);
    const prevTaskStatusRef = useRef(null);

    useEffect(() => {
        const unlockAudio = () => {
            if (!audioCtxRef.current) {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (AudioCtx) audioCtxRef.current = new AudioCtx();
            }
            if (audioCtxRef.current && audioCtxRef.current.state === 'suspended') {
                audioCtxRef.current.resume();
            }
        };
        window.addEventListener('click', unlockAudio);
        window.addEventListener('keydown', unlockAudio);
        return () => {
            window.removeEventListener('click', unlockAudio);
            window.removeEventListener('keydown', unlockAudio);
        };
    }, []);

    const playCompletionSound = async () => {
        try {
            if (!audioCtxRef.current) {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (AudioCtx) audioCtxRef.current = new AudioCtx();
            }
            const ctx = audioCtxRef.current;
            if (ctx && ctx.state === 'suspended') {
                await ctx.resume();
            }
            if (ctx) {
                const playTone = (freq, startTime, duration) => {
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.type = 'sine';
                    osc.frequency.value = freq;
                    gain.gain.setValueAtTime(0.2, startTime);
                    gain.gain.exponentialRampToValueAtTime(0.001, startTime + duration);
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.start(startTime);
                    osc.stop(startTime + duration);
                };
                
                const now = ctx.currentTime;
                playTone(523.25, now, 0.18);       // C5
                playTone(659.25, now + 0.14, 0.18); // E5
                playTone(783.99, now + 0.28, 0.40); // G5
            }
        } catch(e) {
            console.error("Audio chime error:", e);
        }

        // Native browser notification for background tab
        if ("Notification" in window) {
            if (Notification.permission === "granted") {
                new Notification("Escaneo completado", {
                    body: "¡El escaneo botánico ha finalizado exitosamente!",
                    tag: "scan-complete"
                });
            } else if (Notification.permission !== "denied") {
                Notification.requestPermission();
            }
        }
    };

    useEffect(() => {
        if (currentScan?.status === "completed" && prevScanStatusRef.current === "running") {
            playCompletionSound();
            addLocalLogLine(`[SISTEMA] ¡Escaneo completado exitosamente!`, "ok");
        }
        if (currentTask?.status === "finished" && prevTaskStatusRef.current === "running") {
            playCompletionSound();
            addLocalLogLine(`[SISTEMA] ¡Descargas de ${activeFamily} finalizadas!`, "ok");
        }
        prevScanStatusRef.current = currentScan?.status;
        prevTaskStatusRef.current = currentTask?.status;
    }, [currentScan?.status, currentTask?.status]);

    useEffect(() => {
        if (activeFamily && (currentScan?.status === "completed" || currentTask?.status === "finished")) {
            refreshActiveFamilyDetails(activeFamily);
            loadFamilies();
            loadGlobalStats();
        }
    }, [currentScan?.status, currentTask?.status]);

    // Sort families into pinned and unpinned
    const filteredFamilies = familiesData.filter(f => 
        f.name.toLowerCase().includes(familySearch.toLowerCase())
    );
    const pinnedList = filteredFamilies.filter(f => pinnedFamilies.includes(f.name)).sort((a,b) => a.name.localeCompare(b.name));
    const unpinnedList = filteredFamilies.filter(f => !pinnedFamilies.includes(f.name)).sort((a,b) => a.name.localeCompare(b.name));
    const sortedFamilies = [...pinnedList, ...unpinnedList];

    // Filter global stats table
    const globalStatsKeys = Object.keys(globalStats).sort();
    const filteredGlobalStats = globalStatsKeys.filter(name => 
        name.toLowerCase().includes(statsSearch.toLowerCase())
    );

    const scannedFamiliesCount = globalStatsKeys.filter(k => globalStats[k].scanned).length;
    let totalCommonsFiles = 0;
    let totalLocalFiles = 0;
    globalStatsKeys.forEach(k => {
        totalCommonsFiles += globalStats[k].commons_files || 0;
        totalLocalFiles += globalStats[k].local_files || 0;
    });

    // Fetch Album items
    async function loadAlbum() {
        const gen = ++albumLoadGenRef.current;
        setAlbumLoading(true);
        try {
            const resp = await fetch(`${API_BASE}/api/album`);
            if (gen !== albumLoadGenRef.current) return;
            if (resp.ok) {
                const data = await resp.json();
                setAlbumItems(data);
            }
        } catch (e) {
            console.error("Error loading album:", e);
        } finally {
            if (gen === albumLoadGenRef.current) {
                setAlbumLoading(false);
            }
        }
    }

    async function toggleAlbumFavorite(item) {
        const newFav = !item.favorite;
        setAlbumItems(prev => prev.map(x => 
            (x.family === item.family && x.filename === item.filename) 
            ? { ...x, favorite: newFav } 
            : x
        ));

        try {
            const resp = await fetch(`${API_BASE}/api/album/favorite`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    family: item.family,
                    filename: item.filename,
                    favorite: newFav
                })
            });
            if (!resp.ok) throw new Error();
        } catch {
            setAlbumItems(prev => prev.map(x => 
                (x.family === item.family && x.filename === item.filename) 
                ? { ...x, favorite: item.favorite } 
                : x
            ));
        }
    }

    async function renameAlbumItem(item, newName) {
        if (!newName || newName.trim() === "" || newName === item.filename) return;

        let finalName = newName.trim();
        const oldExt = item.filename.substring(item.filename.lastIndexOf('.')).toLowerCase();
        if (!finalName.toLowerCase().endsWith(oldExt)) {
            finalName += oldExt;
        }

        try {
            const resp = await fetch(`${API_BASE}/api/album/rename`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    family: item.family,
                    filename: item.filename,
                    new_filename: finalName
                })
            });

            if (resp.ok) {
                const data = await resp.json();
                setAlbumItems(prev => prev.map(x => 
                    (x.family === item.family && x.filename === item.filename) 
                    ? { ...x, filename: data.new_filename, title: `File:${data.new_filename.substring(0, data.new_filename.length - oldExt.length).replace(/_/g, ' ')}` } 
                    : x
                ));
                if (activeFamily === item.family) {
                    refreshActiveFamilyDetails(activeFamily);
                }
                setRenamingItem(null);
            } else {
                const err = await resp.json();
                alert(`Error al renombrar: ${err.error}`);
            }
        } catch (e) {
            alert(`Error al renombrar: ${e.message}`);
        }
    }

    async function deleteAlbumItem(item) {
        if (!confirm(`¿Estás seguro de que deseas eliminar permanentemente esta ilustración?\n${item.filename}`)) return;

        try {
            const resp = await fetch(`${API_BASE}/api/album/delete`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    family: item.family,
                    filename: item.filename
                })
            });

            if (resp.ok) {
                setAlbumItems(prev => prev.filter(x => !(x.family === item.family && x.filename === item.filename)));
                if (activeFamily === item.family) {
                    refreshActiveFamilyDetails(activeFamily);
                }
            } else {
                const err = await resp.json();
                alert(`Error al eliminar: ${err.error}`);
            }
        } catch (e) {
            alert(`Error al eliminar: ${e.message}`);
        }
    }

    function navigateLightbox(dir) {
        if (!lightbox || lightbox.albumIndex === undefined) return;
        const total = filteredAlbumItems.length;
        if (total === 0) return;

        let newIdx = lightbox.albumIndex + dir;
        if (newIdx < 0) newIdx = total - 1;
        if (newIdx >= total) newIdx = 0;

        const nextItem = filteredAlbumItems[newIdx];
        const imgSrc = `${API_BASE}/api/image/${encodeURIComponent(nextItem.family)}/${encodeURIComponent(nextItem.filename)}`;

        setLightbox({
            src: imgSrc,
            title: nextItem.title,
            commonsUrl: nextItem.description_url,
            albumIndex: newIdx,
            family: nextItem.family,
            filename: nextItem.filename
        });
    }

    const filteredAlbumItems = albumItems.filter(item => {
        const matchesSearch = item.filename.toLowerCase().includes(albumSearch.toLowerCase()) || 
                              item.title.toLowerCase().includes(albumSearch.toLowerCase());
        const matchesFamily = albumFamilyFilter === "all" || item.family.toLowerCase() === albumFamilyFilter.toLowerCase();
        const matchesFavorite = !albumOnlyFavorites || item.favorite;
        const matchesLevel = albumLevelFilter === "all" || (item.taxon?.level || "family") === albumLevelFilter;
        return matchesSearch && matchesFamily && matchesFavorite && matchesLevel;
    });

    return (
        <div className="app-container">
            <aside className={`sidebar ${activeTab !== 'explorer' ? 'sidebar-collapsed' : ''}`}>
                <div className="sidebar-header">
                    <div className={`logo ${activeTab !== 'explorer' ? 'logo-hidden' : ''}`}>
                        <div className="logo-icon-wrap">
                            <i data-lucide="sprout" className="logo-icon"></i>
                        </div>
                        <div className="logo-text">
                            <span className="logo-title">FloraExplorer</span>
                            <div className="logo-sub">Colección Botánica</div>
                        </div>
                    </div>
                    {activeTab !== 'explorer' && (
                        <div className="logo-collapsed-mark">
                            <div className="logo-icon-wrap">
                                <i data-lucide="sprout" className="logo-icon"></i>
                            </div>
                        </div>
                    )}
                    <div className={`nav-tabs ${activeTab !== 'explorer' ? 'nav-tabs-vertical' : ''}`}>
                        <button 
                            className={`nav-tab ${activeTab === 'explorer' ? 'active' : ''}`}
                            onClick={() => navigateToTab('explorer')}
                            title="Explorador"
                        >
                            <i data-lucide="leaf"></i>
                            {activeTab === 'explorer' && <span></span>}
                        </button>
                        <button 
                            className={`nav-tab ${activeTab === 'album' ? 'active' : ''}`}
                            onClick={() => navigateToTab('album')}
                            title="Álbum"
                        >
                            <i data-lucide="image"></i>
                            {activeTab === 'explorer' && <span></span>}
                        </button>
                        <button 
                            className={`nav-tab ${activeTab === 'stats' ? 'active' : ''}`}
                            onClick={() => navigateToTab('stats')}
                            title="Estadísticas"
                        >
                            <i data-lucide="bar-chart-2"></i>
                            {activeTab === 'explorer' && <span></span>}
                        </button>
                    </div>
                </div>

                {activeTab === 'explorer' && (
                    <>
                        <div className="search-container">
                            <i data-lucide="search" className="search-icon"></i>
                            <input 
                                type="text" 
                                id="family-search"
                                placeholder="Buscar familia botánica..." 
                                value={familySearch}
                                onInput={(e) => setFamilySearch(e.target.value)}
                                autoComplete="off"
                            />
                        </div>
                        <div className="sidebar-scrollable">
                            <ul className="family-list">
                                {familiesData.length === 0 ? (
                                    <li className="loading-item">Cargando familias...</li>
                                ) : sortedFamilies.length === 0 ? (
                                    <li className="loading-item">No se encontraron familias.</li>
                                ) : (
                                    sortedFamilies.map((f, idx) => {
                                        const isPinned = pinnedFamilies.includes(f.name);
                                        return (
                                            <li 
                                                key={idx} 
                                                className={`${activeFamily === f.name ? 'active' : ''} ${isPinned ? 'pinned' : ''}`}
                                                onClick={() => selectFamily(f.name)}
                                            >
                                                <span 
                                                    className={`family-pin-btn ${isPinned ? 'pinned' : ''}`}
                                                    onClick={(e) => togglePinFamily(f.name, e)}
                                                    title={isPinned ? "Desanclar" : "Anclar"}
                                                    style={{ marginRight: '6px', cursor: 'pointer', color: isPinned ? 'var(--accent)' : 'inherit', opacity: isPinned ? 1 : 0.4 }}
                                                >
                                                    <i data-lucide="pin" className="small-icon"></i>
                                                </span>
                                                <span className="family-name">{f.name}</span>
                                                <span className="family-badge">{f.downloaded}</span>
                                            </li>
                                        );
                                    })
                                )}
                            </ul>
                        </div>
                    </>
                )}
            </aside>

            <main className="main-content">
                {activeTab === "explorer" ? (
                    activeFamily === null ? (
                        <div className="welcome-container">
                            <div className="welcome-card">
                                <div className="welcome-icon-wrapper">
                                    <i data-lucide="leaf" className="welcome-icon"></i>
                                </div>
                                <h1>Explorador y Scraper de Ilustraciones Botánicas</h1>
                                <p>Selecciona una familia botánica de la barra lateral izquierda para iniciar la exploración de categorías de Wikimedia Commons, descargar las ilustraciones botánicas en alta resolución y estructurar la colección.</p>
                            </div>
                        </div>
                    ) : (
                        <div className="dashboard-view animate-fadeIn">
                            <header className="dashboard-header">
                                <div className="header-title-area">
                                    <div className="header-icon-wrapper">
                                        <i data-lucide="folder-open"></i>
                                    </div>
                                    <div>
                                        <h2 id="active-family-name">{activeFamily}</h2>
                                        <p className="header-path">Ruta de descarga: <span id="active-family-path">{activeFamilyDetails.path}</span></p>
                                    </div>
                                </div>
                                <div className="header-badge" id="active-family-category-link">
                                    <a 
                                        href={`https://commons.wikimedia.org/wiki/Category:Botanical_illustrations_of_${activeFamily}`} 
                                        target="_blank" 
                                        id="commons-link"
                                    >
                                        <span>Wikimedia Commons</span>
                                        <i data-lucide="external-link" className="small-icon"></i>
                                    </a>
                                </div>
                            </header>

                            <section className="stats-grid">
                                <div className="stat-card">
                                    <div className="stat-icon-wrapper blue">
                                        <i data-lucide="database"></i>
                                    </div>
                                    <div className="stat-info">
                                        <span className="stat-label">Archivos Detectados</span>
                                        <h3 id="stat-total">
                                            {currentTask && currentTask.status === "running" ? currentTask.total : activeFamilyDetails.files.length}
                                        </h3>
                                    </div>
                                </div>
                                <div className="stat-card">
                                    <div className="stat-icon-wrapper green">
                                        <i data-lucide="download-cloud"></i>
                                    </div>
                                    <div className="stat-info">
                                        <span className="stat-label">Descargas Completadas</span>
                                        <h3 id="stat-completed">
                                            {currentTask && currentTask.status === "running" ? currentTask.completed : activeFamilyDetails.files.filter(f => f.status === "completed").length}
                                        </h3>
                                    </div>
                                </div>
                                <div className="stat-card">
                                    <div className="stat-icon-wrapper red">
                                        <i data-lucide="alert-triangle"></i>
                                    </div>
                                    <div className="stat-info">
                                        <span className="stat-label">Errores / Bloqueos</span>
                                        <h3 id="stat-errors">
                                            {currentTask && currentTask.status === "running" ? currentTask.errors : activeFamilyDetails.files.filter(f => f.status === "error").length}
                                        </h3>
                                    </div>
                                </div>
                            </section>

                            <div className="panels-layout" style={{ minHeight: '380px', height: 'auto', alignItems: 'flex-start' }}>
                                <div className="panel flex-3" style={{ height: treePanelExpanded ? 'auto' : '380px' }}>
                                    <div className="panel-header">
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                            <div style={{ width: '28px', height: '28px', borderRadius: '6px', background: 'rgba(16,185,129,0.12)', border: '1px solid rgba(16,185,129,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                                <i data-lucide="folder-open" style={{ width: '14px', height: '14px', color: 'var(--accent)' }}></i>
                                            </div>
                                            <h3>Escanear</h3>
                                        </div>
                                    </div>
                                    <div className="control-box">
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                            <span style={{ fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)' }}>Profundidad de escaneo</span>
                                            <div className="scan-settings">
                                                <select 
                                                    id="scan-depth" 
                                                    value={scanDepth} 
                                                    onChange={(e) => setScanDepth(parseInt(e.target.value))}
                                                >
                                                    <option value={1}>Nivel 1 — Directas / Géneros</option>
                                                    <option value={2}>Nivel 2 — Especies</option>
                                                    <option value={3}>Nivel 3 — Profundo (Recomendado)</option>
                                                </select>
                                                <button 
                                                    className="btn btn-primary" 
                                                    id="btn-scan" 
                                                    onClick={scanActiveFamily}
                                                    disabled={currentScan?.status === "running"}
                                                >
                                                    {currentScan?.status === "running" ? (
                                                        <>
                                                            <i data-lucide="loader" className="logo-icon spin"></i>
                                                            <span>Escaneando Pywikibot...</span>
                                                        </>
                                                    ) : (
                                                        <>
                                                            <i data-lucide="refresh-cw"></i>
                                                            <span>Escanear Categoría</span>
                                                        </>
                                                    )}
                                                </button>
                                            </div>
                                        </div>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', paddingTop: '12px', borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                                            <span style={{ fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)' }}>Descargas</span>
                                            <div className="actions-row">
                                                <button 
                                                    className="btn btn-success" 
                                                    id="btn-download" 
                                                    onClick={startDownloadActiveFamily}
                                                    disabled={!activeFamilyDetails.scanned || currentTask?.status === "running"}
                                                >
                                                    <i data-lucide="download-cloud"></i>
                                                    <span>Iniciar Descargas</span>
                                                </button>
                                                <button 
                                                    className="btn btn-danger" 
                                                    id="btn-pause" 
                                                    onClick={pauseDownloadActiveFamily}
                                                    disabled={currentTask?.status !== "running"}
                                                >
                                                    <i data-lucide="pause"></i>
                                                    <span>Pausar</span>
                                                </button>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Category Tree View with Expansion fitting controls */}
                                    <div className="tree-container" style={{ padding: '16px 24px' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                <i data-lucide="git-branch" style={{ width: '14px', height: '14px', color: 'var(--accent)' }}></i>
                                                <h4 className="section-title" style={{ margin: 0 }}>Estructura Commons</h4>
                                            </div>
                                            <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                                                <button className="btn btn-outline" style={{ padding: '3px 10px', fontSize: '14px', fontWeight: 700 }} onClick={() => setTreeExpandedAll(true)} title="Expandir todo el árbol (+)">
                                                    +
                                                </button>
                                                <button className="btn btn-outline" style={{ padding: '3px 10px', fontSize: '14px', fontWeight: 700 }} onClick={() => setTreeExpandedAll(false)} title="Colapsar todo el árbol (-)">
                                                    -
                                                </button>
                                                <button className="btn btn-outline" style={{ padding: '3px 10px', fontSize: '14px', fontWeight: 700 }} onClick={() => setTreePanelExpanded(!treePanelExpanded)} title={treePanelExpanded ? "Reducir recuadro (flecha arriba)" : "Ampliar recuadro (flecha abajo)"}>
                                                    {treePanelExpanded ? "↑" : "↓"}
                                                </button>
                                            </div>
                                        </div>
                                        <div className="tree-wrapper" id="tree-wrapper" style={{ maxHeight: treePanelExpanded ? '550px' : '170px', overflowY: 'auto' }}>
                                            {activeFamilyDetails.tree ? (
                                                <TreeNode node={activeFamilyDetails.tree} forceExpanded={treeExpandedAll} />
                                            ) : (
                                                <div className="no-tree">Haz clic en "Escanear Categoría" para listar la estructura recursiva.</div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div className="panel flex-2 flex-col" style={{ height: '380px', position: 'sticky', top: '10px' }}>
                                    <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                        <h3></h3>
                                        <a 
                                            href={`${API_BASE}/api/log`} 
                                            target="_blank" 
                                            rel="noopener noreferrer" 
                                            className="btn btn-outline" 
                                            style={{ fontSize: '11px', padding: '3px 8px', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '4px' }}
                                            title="Ver / Descargar archivo de registros persistente (app.log)"
                                        >
                                            <i data-lucide="file-text" style={{ width: '12px', height: '12px' }}></i>
                                            <span>Ver Log Completo</span>
                                        </a>
                                    </div>
                                    <div className="terminal" id="terminal-log" ref={terminalRef} style={{ flex: 1, overflowY: 'auto' }}>
                                        {logs.map((log, idx) => {
                                            const isErr = log.includes("[ERROR]") || log.includes("Error");
                                            const isOk = log.includes("[OK]");
                                            const styleClass = isErr ? "error" : (isOk ? "ok" : "system");
                                            return (
                                                <div key={idx} className={`terminal-line ${styleClass}`}>
                                                    {log}
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            </div>

                            {/* Wikipedia Panel */}
                            <section className="wikipedia-panel panel" style={{ marginTop: '24px' }}>
                                <div className="panel-header flex-row" style={{ justifyContent: 'space-between', alignItems: 'center', display: 'flex', width: '100%' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                        <i data-lucide="book-open" style={{ color: 'var(--accent)', width: '18px', height: '18px' }}></i>
                                        <h3 style={{ margin: 0 }}>Ficha</h3>
                                    </div>
                                    <div className="wiki-controls" style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                                        <button className="btn btn-outline" style={{ padding: '3px 10px', fontSize: '14px', fontWeight: 700 }} onClick={() => setWikiPanelExpanded(!wikiPanelExpanded)} title={wikiPanelExpanded ? "Reducir recuadro (flecha arriba)" : "Ampliar recuadro (flecha abajo)"}>
                                            {wikiPanelExpanded ? "↑" : "↓"}
                                        </button>
                                        {wikiCustomSearchVisible && (
                                            <input 
                                                type="text" 
                                                placeholder="Buscar otro término..." 
                                                value={wikiQuery}
                                                onInput={(e) => setWikiQuery(e.target.value)}
                                                onKeyDown={(e) => {
                                                    if (e.key === "Enter" && wikiQuery.trim()) {
                                                        downloadWikipediaArticle(wikiQuery);
                                                    }
                                                }}
                                                style={{ backgroundColor: 'var(--bg-input)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '6px 10px', color: 'white', fontSize: '12px', width: '150px' }}
                                            />
                                        )}
                                        <button 
                                            className="btn btn-outline" 
                                            style={{ padding: '8px' }} 
                                            onClick={() => setWikiCustomSearchVisible(!wikiCustomSearchVisible)}
                                            title="Buscar término personalizado"
                                        >
                                            <i data-lucide="search" className="small-icon"></i>
                                        </button>
                                        <button 
                                            className="btn btn-outline"
                                            onClick={() => downloadWikipediaArticle(wikiQuery || null)}
                                            disabled={wikiLoading}
                                        >
                                            {wikiLoading ? (
                                                <>
                                                    <i data-lucide="loader" className="small-icon spin"></i>
                                                    <span>Descargando...</span>
                                                </>
                                            ) : activeFamilyDetails.wikipedia_url ? (
                                                <>
                                                    <i data-lucide="refresh-cw" className="small-icon"></i>
                                                    <span>Actualizar Artículo</span>
                                                </>
                                            ) : (
                                                <>
                                                    <i data-lucide="download" className="small-icon"></i>
                                                    <span>Descargar Artículo</span>
                                                </>
                                            )}
                                        </button>
                                    </div>
                                </div>
                                <div className="wiki-body" id="wiki-body" style={{ height: wikiPanelExpanded ? '650px' : '380px', resize: 'vertical', overflow: 'auto', padding: 0, backgroundColor: '#05080e', borderTop: '1px solid var(--border-color)' }}>
                                    {activeFamilyDetails.wikipedia_url ? (
                                        <iframe 
                                            key={activeFamilyDetails.wikipedia_url}
                                            src={`${API_BASE}${activeFamilyDetails.wikipedia_url}${activeFamilyDetails.wikipedia_url.includes('?') ? '' : '?t=' + Date.now()}`}
                                            onLoad={(e) => {
                                                try {
                                                    const iframeWin = e.target.contentWindow;
                                                    const iframeDoc = e.target.contentDocument || (iframeWin && iframeWin.document);
                                                    if (!iframeDoc) return;
                                                    
                                                    iframeDoc.addEventListener('click', (evt) => {
                                                        const a = evt.target.closest('a');
                                                        if (a) {
                                                            const href = a.getAttribute('href') || '';
                                                            const dataPage = a.getAttribute('data-wiki-page');
                                                            
                                                            let targetTerm = null;
                                                            if (dataPage) {
                                                                targetTerm = dataPage;
                                                            } else if (href.includes('/wiki/')) {
                                                                const parts = href.split('/wiki/');
                                                                if (parts.length > 1) {
                                                                    targetTerm = parts[1].split('#')[0];
                                                                }
                                                            }
                                                            
                                                            if (targetTerm) {
                                                                evt.preventDefault();
                                                                evt.stopPropagation();
                                                                const cleanTerm = decodeURIComponent(targetTerm).replace(/_/g, ' ');
                                                                downloadWikipediaArticle(cleanTerm);
                                                            }
                                                        }
                                                    }, true);
                                                } catch(err) {
                                                    // Silently ignore cross-origin SecurityError in dev
                                                    // (Vite:4321 vs Flask:5000). Wiki links still work via Flask proxy.
                                                }
                                            }}
                                            style={{ width: '100%', height: '100%', border: 0, backgroundColor: '#0b0f19' }}
                                        ></iframe>
                                    ) : (
                                        <div className="empty-wiki" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)', gap: '12px', fontStyle: 'italic', fontSize: '13px' }}>
                                            <i data-lucide="book-open" style={{ width: '32px', height: '32px', strokeWidth: 1.5 }}></i>
                                            <span>No se ha descargado el artículo científico de Wikipedia para esta familia. Haz clic en "Descargar Artículo".</span>
                                        </div>
                                    )}
                                </div>
                            </section>

                            {/* Gallery Section */}
                            <section className="gallery-panel" style={{ marginTop: '24px' }}>
                                {(() => {
                                    const completedFiles = activeFamilyDetails.files.filter(f => f.status === "completed");
                                    if (completedFiles.length === 0) {
                                        return (
                                            <>
                                                <div className="panel-header flex-row">
                                                    <h3>Galería de Ilustraciones Descargadas</h3>
                                                    <span className="gallery-count" id="gallery-count">0 imágenes</span>
                                                </div>
                                                <div className="empty-gallery">No hay ilustraciones descargadas en local para esta familia. Haz clic en "Iniciar Descargas".</div>
                                            </>
                                        );
                                    }

                                    function buildCardData(file, idx) {
                                        const titleClean = file.title.replace("File:", "");
                                        let base_name = sanitizeFilenameForJS(file.title);
                                        let ext = ".jpg";
                                        const dotIdx = file.title.lastIndexOf('.');
                                        if (dotIdx !== -1) ext = file.title.substring(dotIdx);
                                        if (base_name.toLowerCase().endsWith(ext.toLowerCase()))
                                            base_name = base_name.substring(0, base_name.length - ext.length);
                                        const imgFilename = base_name + ext;
                                        const imgSrc = `${API_BASE}/api/image/${encodeURIComponent(activeFamily)}/${encodeURIComponent(imgFilename)}`;
                                        const thumbSrc = `${API_BASE}/api/thumbnail/${encodeURIComponent(activeFamily)}/${encodeURIComponent(imgFilename)}`;
                                        const isPdf = ext.toLowerCase() === ".pdf";
                                        return { file, idx, titleClean, imgSrc, thumbSrc, isPdf, imgFilename };
                                    }

                                    const familyLevel = [];
                                    const unidentified = [];
                                    const byGenus = {};

                                    completedFiles.forEach((file, idx) => {
                                        const taxon = file.taxon || { level: "family", genus: null, species: null };
                                        const card = buildCardData(file, idx);
                                        card.taxon = taxon;

                                        if (taxon.level === "family") {
                                            familyLevel.push(card);
                                        } else if (taxon.level === "unidentified" && !taxon.genus) {
                                            unidentified.push(card);
                                        } else {
                                            const genus = taxon.genus || "Sin género";
                                            if (!byGenus[genus]) byGenus[genus] = { genus, genus_cards: [], by_species: {} };
                                            if (taxon.level === "genus") {
                                                byGenus[genus].genus_cards.push(card);
                                            } else if (taxon.level === "unidentified") {
                                                const key = `Unidentified ${genus}`;
                                                if (!byGenus[genus].by_species[key]) byGenus[genus].by_species[key] = [];
                                                byGenus[genus].by_species[key].push(card);
                                            } else {
                                                const sp = taxon.species || taxon.display;
                                                if (!byGenus[genus].by_species[sp]) byGenus[genus].by_species[sp] = [];
                                                byGenus[genus].by_species[sp].push(card);
                                            }
                                        }
                                    });

                                    const sortedGenera = Object.keys(byGenus).sort();

                                    function GalleryCard({ card }) {
                                        return (
                                            <div
                                                className="gallery-card"
                                                onClick={() => setLightbox({ src: card.imgSrc, title: card.file.title, commonsUrl: card.file.description_url, family: activeFamily, filename: card.imgFilename })}
                                            >
                                                <div className="img-container" style={{ position: 'relative' }}>
                                                    <img src={card.thumbSrc} alt={card.titleClean} loading="lazy" />
                                                    {card.isPdf && (
                                                        <span style={{ position: 'absolute', top: '6px', right: '6px', background: 'rgba(239, 68, 68, 0.85)', color: 'white', fontSize: '9px', fontWeight: 700, padding: '2px 6px', borderRadius: '4px', backdropFilter: 'blur(4px)', border: '1px solid rgba(255,255,255,0.2)' }}>
                                                            PDF
                                                        </span>
                                                    )}
                                                </div>
                                                <div className="card-info">
                                                    <span className="card-title">{card.titleClean}</span>
                                                </div>
                                            </div>
                                        );
                                    }

                                    const [allOpen, setAllOpen] = useState(null);

                                    const expandAll = () => setAllOpen(v => v === true ? null : true);
                                    const collapseAll = () => setAllOpen(v => v === false ? null : false);

                                    return (
                                        <>
                                            <div className="panel-header flex-row" style={{ marginBottom: '20px' }}>
                                                <h3>Galería</h3>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginLeft: 'auto' }}>
                                                    <span className="gallery-count" id="gallery-count">{completedFiles.length} imágenes</span>
                                                    <button
                                                        onClick={expandAll}
                                                        title="Expandir todos los géneros"
                                                        style={{ display:'flex', alignItems:'center', gap:'4px', padding:'4px 10px', borderRadius:'6px', border:'1px solid rgba(74,222,128,0.3)', background:'rgba(74,222,128,0.07)', color:'#4ade80', fontSize:'12px', fontWeight:600, cursor:'pointer' }}
                                                        onMouseEnter={e => e.currentTarget.style.background='rgba(74,222,128,0.18)'}
                                                        onMouseLeave={e => e.currentTarget.style.background='rgba(74,222,128,0.07)'}
                                                    >
                                                        <span style={{fontSize:'15px',lineHeight:1}}>+</span> 
                                                    </button>
                                                    <button
                                                        onClick={collapseAll}
                                                        title="Colapsar todos los géneros"
                                                        style={{ display:'flex', alignItems:'center', gap:'4px', padding:'4px 10px', borderRadius:'6px', border:'1px solid rgba(251,146,60,0.3)', background:'rgba(251,146,60,0.07)', color:'#fb923c', fontSize:'12px', fontWeight:600, cursor:'pointer' }}
                                                        onMouseEnter={e => e.currentTarget.style.background='rgba(251,146,60,0.18)'}
                                                        onMouseLeave={e => e.currentTarget.style.background='rgba(251,146,60,0.07)'}
                                                    >
                                                        <span style={{fontSize:'15px',lineHeight:1}}>−</span> 
                                                    </button>
                                                </div>
                                            </div>

                                            {familyLevel.length > 0 && (
                                                <div style={{ marginBottom: '32px' }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
                                                        <span style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--accent)', padding: '3px 8px', borderRadius: '4px', background: 'rgba(138,180,248,0.08)', border: '1px solid rgba(138,180,248,0.2)' }}>Familia</span>
                                                        <h4 style={{ margin: 0, fontSize: '15px', color: '#fff', fontStyle: 'italic' }}>{activeFamily}</h4>
                                                        <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>({familyLevel.length})</span>
                                                    </div>
                                                    <div className="gallery-grid">{familyLevel.map((card, i) => <GalleryCard key={i} card={card} />)}</div>
                                                </div>
                                            )}

                                            {sortedGenera.map(genus => {
                                                const gData = byGenus[genus];
                                                const sortedSpecies = Object.keys(gData.by_species).sort();
                                                const genusTotal = gData.genus_cards.length + sortedSpecies.reduce((s, sp) => s + gData.by_species[sp].length, 0);
                                                return (
                                                    <CollapsibleGenus
                                                        key={genus}
                                                        id={`${activeFamily}-${genus}`}
                                                        forceOpen={allOpen}
                                                        label="Género"
                                                        badge={genus}
                                                        count={genusTotal}
                                                        color="#4ade80"
                                                        bgColor="rgba(74,222,128,0.08)"
                                                        borderColor="rgba(74,222,128,0.2)"
                                                    >
                                                        {gData.genus_cards.length > 0 && (
                                                            <div style={{ marginBottom: '16px' }}>
                                                                <div className="gallery-grid">{gData.genus_cards.map((card, i) => <GalleryCard key={i} card={card} />)}</div>
                                                            </div>
                                                        )}

                                                        {sortedSpecies.map(sp => (
                                                            <div key={sp} style={{ marginBottom: '16px', paddingLeft: '16px', borderLeft: '2px solid rgba(96,165,250,0.2)' }}>
                                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                                                                    <span style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: sp.startsWith("Unidentified") ? '#fb923c' : '#60a5fa', padding: '2px 6px', borderRadius: '3px', background: sp.startsWith("Unidentified") ? 'rgba(251,146,60,0.08)' : 'rgba(96,165,250,0.08)', border: `1px solid ${sp.startsWith("Unidentified") ? 'rgba(251,146,60,0.25)' : 'rgba(96,165,250,0.25)'}` }}>{sp.startsWith("Unidentified") ? "No id." : "Especie"}</span>
                                                                    <span style={{ fontSize: '13px', color: '#e2e8f0', fontStyle: 'italic' }}>{sp}</span>
                                                                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>({gData.by_species[sp].length})</span>
                                                                </div>
                                                                <div className="gallery-grid">{gData.by_species[sp].map((card, i) => <GalleryCard key={i} card={card} />)}</div>
                                                            </div>
                                                        ))}
                                                    </CollapsibleGenus>
                                                );
                                            })}

                                            {unidentified.length > 0 && (
                                                <CollapsibleGenus
                                                    id={`${activeFamily}-unidentified`}
                                                    forceOpen={allOpen}
                                                    label="No identificadas"
                                                    badge=""
                                                    count={unidentified.length}
                                                    color="#fb923c"
                                                    bgColor="rgba(251,146,60,0.08)"
                                                    borderColor="rgba(251,146,60,0.25)"
                                                >
                                                    <div className="gallery-grid">{unidentified.map((card, i) => <GalleryCard key={i} card={card} />)}</div>
                                                </CollapsibleGenus>
                                            )}
                                        </>
                                    );
                                })()}
                            </section>
                        </div>
                    )
                ) : activeTab === "album" ? (
                    <div className="album-view animate-fadeIn">
                        {/* Sticky Filter Bar */}
                        <div className="album-filterbar">
                            <div className="album-search-wrap">
                                <i data-lucide="search" className="album-search-icon"></i>
                                <input
                                    type="text"
                                    id="album-search"
                                    placeholder="Buscar ilustración..."
                                    value={albumSearch}
                                    onInput={(e) => {
                                        setAlbumSearch(e.target.value);
                                        updateHash('album', albumFamilyFilter !== 'all' ? albumFamilyFilter : null);
                                    }}
                                    autoComplete="off"
                                    className="album-search-input"
                                />
                                {albumSearch && (
                                    <button
                                        onClick={() => setAlbumSearch("")}
                                        className="album-search-clear"
                                        title="Limpiar búsqueda"
                                    >
                                        <i data-lucide="x" style={{ width: '12px', height: '12px' }}></i>
                                    </button>
                                )}
                            </div>

                            <div className="album-filter-divider"></div>

                            <div className="album-select-wrap">
                                <i data-lucide="folder" style={{ width: '13px', height: '13px', color: 'var(--text-muted)', flexShrink: 0 }}></i>
                                <select
                                    value={albumFamilyFilter}
                                    onChange={(e) => {
                                        const fam = e.target.value;
                                        setAlbumFamilyFilter(fam);
                                        updateHash('album', fam !== 'all' ? fam : null);
                                    }}
                                    className="album-select"
                                >
                                    <option value="all">Todas las familias</option>
                                    {familiesData.map((f, idx) => (
                                        <option key={idx} value={f.name}>{f.name}</option>
                                    ))}
                                </select>
                            </div>

                            <div className="album-select-wrap">
                                <i data-lucide="git-branch" style={{ width: '13px', height: '13px', color: 'var(--text-muted)', flexShrink: 0 }}></i>
                                <select
                                    value={albumLevelFilter}
                                    onChange={(e) => setAlbumLevelFilter(e.target.value)}
                                    className="album-select"
                                >
                                    <option value="all">Todos los niveles</option>
                                    <option value="family">Familia</option>
                                    <option value="genus">Género</option>
                                    <option value="species">Especie</option>
                                    <option value="variety">Variedad</option>
                                    <option value="unidentified">No identificado</option>
                                </select>
                            </div>

                            <div className="album-filter-divider"></div>

                            <button
                                className={`album-fav-toggle ${albumOnlyFavorites ? 'active' : ''}`}
                                onClick={() => setAlbumOnlyFavorites(!albumOnlyFavorites)}
                                title="Mostrar solo favoritos"
                            >
                                <i data-lucide="star" style={{ width: '14px', height: '14px', fill: albumOnlyFavorites ? 'currentColor' : 'none' }}></i>
                                <span>Favoritos</span>
                            </button>
                        </div>

                        {/* Stats Strip */}
                        {!albumLoading && (() => {
                            const counts = filteredAlbumItems.reduce((acc, item) => {
                                const lvl = item.taxon?.level || 'family';
                                acc[lvl] = (acc[lvl] || 0) + 1;
                                return acc;
                            }, {});
                            const chips = [
                                { lvl: 'family',      color: '#8ab4f8', label: 'Familias',    icon: '🌿', count: counts.family },
                                { lvl: 'genus',       color: '#4ade80', label: 'Géneros',     icon: '🌱', count: counts.genus },
                                { lvl: 'species',     color: '#60a5fa', label: 'Especies',    icon: '🍃', count: counts.species },
                                { lvl: 'variety',     color: '#c084fc', label: 'Variedades',  icon: '🔬', count: counts.variety },
                                { lvl: 'unidentified',color: '#fb923c', label: 'Sin id.',     icon: '❓', count: counts.unidentified },
                            ].filter(c => c.count);
                            return (
                                <div className="album-stats-strip">
                                    {chips.map(c => (
                                        <button
                                            key={c.lvl}
                                            className={`album-stat-chip ${albumLevelFilter === c.lvl ? 'chip-active' : ''}`}
                                            style={{ '--chip-color': c.color }}
                                            onClick={() => setAlbumLevelFilter(albumLevelFilter === c.lvl ? 'all' : c.lvl)}
                                            title={`Filtrar: ${c.label}`}
                                        >
                                            <span className="chip-icon">{c.icon}</span>
                                            <span className="chip-count">{c.count}</span>
                                            <span className="chip-label">{c.label}</span>
                                        </button>
                                    ))}
                                    <span className="album-total-count">
                                        {filteredAlbumItems.length} total
                                    </span>
                                </div>
                            );
                        })()}

                        {/* Gallery Grid */}
                        <section className="album-gallery-section">
                            {albumLoading ? (
                                <div className="album-loading">
                                    <Spinner size={36} className="spin" style={{ color: 'var(--accent)' }} />
                                    <span>Cargando colección...</span>
                                </div>
                            ) : filteredAlbumItems.length === 0 ? (
                                <div className="album-empty">
                                    <AlbumIcon name="image-off" size={40} className="album-empty-icon" />
                                    <p>No se encontraron ilustraciones con los filtros actuales.</p>
                                    <button className="btn btn-outline" onClick={() => { setAlbumSearch(''); setAlbumFamilyFilter('all'); setAlbumLevelFilter('all'); setAlbumOnlyFavorites(false); updateHash('album'); }}>
                                        Limpiar filtros
                                    </button>
                                </div>
                            ) : (
                                <div className="album-grid">
                                    {filteredAlbumItems.map((item, idx) => {
                                        const titleClean = item.title.replace("File:", "");
                                        const imgSrc = `${API_BASE}/api/image/${encodeURIComponent(item.family)}/${encodeURIComponent(item.filename)}`;
                                        const thumbSrc = `${API_BASE}/api/thumbnail/${encodeURIComponent(item.family)}/${encodeURIComponent(item.filename)}`;
                                        const sizeKB = (item.size / 1024).toFixed(0);
                                        const lvlColors = { family: '#8ab4f8', genus: '#4ade80', species: '#60a5fa', variety: '#c084fc', unidentified: '#fb923c' };
                                        const lvlLabels = { family: 'Familia', genus: 'Género', species: 'Especie', variety: 'Variedad', unidentified: 'Sin id.' };
                                        const lvl = item.taxon?.level || 'family';
                                        const col = lvlColors[lvl] || '#8ab4f8';
                                        const displayName = item.taxon?.display || item.family;
                                        const isPdf = item.filename.toLowerCase().endsWith('.pdf');

                                        return (
                                            <div key={idx} className="album-card">
                                                <div
                                                    className="album-card-img"
                                                    onClick={() => setLightbox({ src: imgSrc, title: item.title, commonsUrl: item.description_url, albumIndex: idx, family: item.family, filename: item.filename })}
                                                >
                                                    <img
                                                         src={thumbSrc}
                                                         alt={titleClean}
                                                         loading="lazy"
                                                         onError={(e) => {
                                                             e.target.style.display = 'none';
                                                             const placeholder = e.target.parentNode.querySelector('.album-img-error');
                                                             if (placeholder) placeholder.style.display = 'flex';
                                                         }}
                                                     />
                                                     {isPdf && (
                                                         <span style={{ position: 'absolute', top: '8px', right: '8px', background: 'rgba(239, 68, 68, 0.85)', color: 'white', fontSize: '9px', fontWeight: 700, padding: '2px 6px', borderRadius: '4px', backdropFilter: 'blur(4px)', border: '1px solid rgba(255,255,255,0.2)', zIndex: 5 }}>
                                                             PDF
                                                         </span>
                                                     )}
                                                    <div className="album-img-error">
                                                        <AlbumIcon name="image-off" size={24} />
                                                        <span>Sin vista previa</span>
                                                    </div>
                                                    <div className="album-card-overlay">
                                                        <button
                                                            className={`album-action-btn ${item.favorite ? 'fav-active' : ''}`}
                                                            onClick={(e) => { e.stopPropagation(); toggleAlbumFavorite(item); }}
                                                            title={item.favorite ? "Quitar favorito" : "Marcar favorito"}
                                                        >
                                                            <AlbumIcon name="star" size={16} filled={item.favorite} />
                                                        </button>
                                                        <button
                                                            className="album-action-btn"
                                                            onClick={(e) => { e.stopPropagation(); setRenamingItem(item); }}
                                                            title="Renombrar"
                                                        >
                                                            <AlbumIcon name="edit-2" size={16} />
                                                        </button>
                                                        <button
                                                            className="album-action-btn danger"
                                                            onClick={(e) => { e.stopPropagation(); deleteAlbumItem(item); }}
                                                            title="Eliminar"
                                                        >
                                                            <AlbumIcon name="trash-2" size={16} />
                                                        </button>
                                                    </div>
                                                    {item.favorite && (
                                                        <div className="album-fav-star">
                                                            <AlbumIcon name="star" size={12} filled />
                                                        </div>
                                                    )}
                                                    <div className="album-family-chip">{item.family}</div>
                                                </div>

                                                <div className="album-card-info">
                                                    <div className="album-card-taxon">
                                                        <span className="album-taxon-badge" style={{ color: col, background: `${col}15`, border: `1px solid ${col}35` }}>
                                                            {lvlLabels[lvl]}
                                                        </span>
                                                        <span className="album-taxon-name" style={{ color: col }}>
                                                            {displayName}
                                                        </span>
                                                    </div>
                                                    <p className="album-card-filename" title={titleClean}>{titleClean}</p>
                                                    <span className="album-card-size">{sizeKB} KB</span>
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </section>

                        {renamingItem && (
                            <div className="modal" id="rename-modal" style={{ display: 'flex', zIndex: 10000 }}>
                                <div className="modal-overlay" onClick={() => setRenamingItem(null)}></div>
                                <div className="modal-content-wrapper" onClick={(e) => e.stopPropagation()} style={{ width: '90%', maxWidth: '450px', padding: '24px' }}>
                                    <button className="modal-close" onClick={() => setRenamingItem(null)}>
                                        <i data-lucide="x"></i>
                                    </button>
                                    <div className="modal-body" style={{ padding: 0 }}>
                                        <h3 style={{ margin: '0 0 8px 0', fontSize: '18px', color: '#fff' }}>Renombrar Ilustración</h3>
                                        <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '16px' }}>
                                            Renombrarás el archivo físico de la familia <strong>{renamingItem.family}</strong> en tu disco.
                                        </p>
                                        <div style={{ marginBottom: '20px' }}>
                                            <label style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Nombre actual:</label>
                                            <div style={{ fontSize: '13px', color: '#fff', wordBreak: 'break-all', padding: '8px 12px', background: 'rgba(255,255,255,0.02)', borderRadius: '4px', border: '1px solid var(--border-color)' }}>
                                                {renamingItem.filename}
                                            </div>
                                        </div>
                                        <div style={{ marginBottom: '24px' }}>
                                            <label style={{ fontSize: '11px', color: 'var(--accent)', display: 'block', marginBottom: '6px' }}>Nuevo nombre:</label>
                                            <input 
                                                type="text" 
                                                placeholder="Ingresa el nuevo nombre..."
                                                defaultValue={renamingItem.filename.substring(0, renamingItem.filename.lastIndexOf('.'))}
                                                id="new-name-input"
                                                autoComplete="off"
                                                style={{ width: '100%', padding: '10px 12px', background: 'var(--bg-input)', border: '1px solid var(--border-color)', borderRadius: '8px', color: '#fff', fontSize: '13px' }}
                                                onKeyDown={(e) => {
                                                    if (e.key === "Enter") {
                                                        const val = e.target.value;
                                                        renameAlbumItem(renamingItem, val);
                                                    }
                                                }}
                                            />
                                        </div>
                                        <div className="flex-row gap-16" style={{ justifyContent: 'flex-end', display: 'flex' }}>
                                            <button className="btn btn-outline" onClick={() => setRenamingItem(null)}>Cancelar</button>
                                            <button 
                                                className="btn btn-primary" 
                                                onClick={() => {
                                                    const val = document.getElementById("new-name-input").value;
                                                    renameAlbumItem(renamingItem, val);
                                                }}
                                            >
                                                Guardar
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                ) : (
                    <div className="global-stats-view">
                        <div className="dashboard-header">
                            <div className="header-meta">
                                <h2>Estadísticas Globales de la Colección</h2>
                                <span className="path-label">Control consolidado de las 395 familias botánicas</span>
                            </div>
                        </div>

                        <section className="stats-grid">
                            <div className="stat-card">
                                <div className="stat-icon-wrapper blue">
                                    <i data-lucide="folder-check"></i>
                                </div>
                                <div className="stat-info">
                                    <span className="stat-label">Familias Escaneadas</span>
                                    <h3 id="global-scanned-count">
                                        {scannedFamiliesCount} / {globalStatsKeys.length}
                                    </h3>
                                </div>
                            </div>
                            <div className="stat-card">
                                <div className="stat-icon-wrapper green">
                                    <i data-lucide="image"></i>
                                </div>
                                <div className="stat-info">
                                    <span className="stat-label">Fotos en Commons</span>
                                    <h3 id="global-commons-files">
                                        {totalCommonsFiles.toLocaleString()}
                                    </h3>
                                </div>
                            </div>
                            <div className="stat-card">
                                <div className="stat-icon-wrapper green">
                                    <i data-lucide="download"></i>
                                </div>
                                <div className="stat-info">
                                    <span className="stat-label">Fotos Descargadas</span>
                                    <h3 id="global-local-files">
                                        {totalLocalFiles.toLocaleString()}
                                    </h3>
                                </div>
                            </div>
                        </section>

                        <div className="panel flex-col batch-scan-card">
                            <div className="panel-header">
                                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                    <div style={{ width: '28px', height: '28px', borderRadius: '6px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.25)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                        <i data-lucide="layers" style={{ width: '14px', height: '14px', color: '#60a5fa' }}></i>
                                    </div>
                                    <div>
                                        <h3 style={{ fontSize: '14px', fontWeight: 600 }}>Escaneo en Lote</h3>
                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '1px' }}>Analiza todas las familias secuencialmente</div>
                                    </div>
                                </div>
                                {batchScan.active && (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--accent)', fontWeight: 500 }}>
                                        <i data-lucide="loader" className="spin" style={{ width: '13px', height: '13px' }}></i>
                                        <span>{batchScan.processed} / {batchScan.total}</span>
                                    </div>
                                )}
                            </div>
                            <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                    <span style={{ fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)' }}>Profundidad</span>
                                    <div style={{ display: 'flex', gap: '6px' }}>
                                        {[{v:0,label:'Raíz'},{v:1,label:'Géneros'},{v:2,label:'Especies'},{v:3,label:'Completo'}].map(({v, label}) => (
                                            <button
                                                key={v}
                                                onClick={() => setBatchScanDepth(v)}
                                                style={{
                                                    flex: 1, padding: '6px 4px', fontSize: '11px', fontWeight: 600,
                                                    borderRadius: '5px', border: `1px solid ${batchScanDepth === v ? 'rgba(96,165,250,0.5)' : 'var(--border-color)'}`,
                                                    background: batchScanDepth === v ? 'rgba(59,130,246,0.15)' : 'transparent',
                                                    color: batchScanDepth === v ? '#60a5fa' : 'var(--text-muted)',
                                                    cursor: 'pointer', transition: 'all 0.15s ease', textAlign: 'center'
                                                }}
                                            >
                                                <span style={{ display: 'block', fontSize: '13px', fontWeight: 700 }}>{v}</span>
                                                <span style={{ display: 'block', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.04em', marginTop: '1px' }}>{label}</span>
                                            </button>
                                        ))}
                                    </div>
                                </div>
                                <div style={{ display: 'flex', gap: '8px' }}>
                                    <button 
                                        className="btn btn-primary" 
                                        id="btn-batch-scan" 
                                        onClick={startBatchScan}
                                        disabled={batchScan.active}
                                        style={{ flex: 1 }}
                                    >
                                        {batchScan.active ? (
                                            <><i data-lucide="loader" className="spin" style={{ width: '13px', height: '13px' }}></i><span>Escaneando...</span></>
                                        ) : (
                                            <><i data-lucide="refresh-cw" style={{ width: '13px', height: '13px' }}></i><span>Iniciar Scan</span></>
                                        )}
                                    </button>
                                    <button 
                                        className="btn btn-danger" 
                                        id="btn-batch-stop" 
                                        onClick={stopBatchScan}
                                        disabled={!batchScan.active}
                                        style={{ flex: 1 }}
                                    >
                                        <i data-lucide="square" style={{ width: '13px', height: '13px' }}></i>
                                        <span>Detener</span>
                                    </button>
                                </div>
                            </div>
                        </div>

                        <div className="panel flex-col" style={{ marginTop: '24px', flex: 1 }}>
                            <div className="panel-header flex-row" style={{ justifyContent: 'space-between', padding: '20px 24px', alignItems: 'center' }}>
                                <h3 style={{ margin: 0 }}>Tabla Comparativa de la Colección</h3>
                                <div className="search-container" style={{ margin: 0, width: '250px' }}>
                                    <i data-lucide="search" className="search-icon"></i>
                                    <input 
                                        type="text" 
                                        placeholder="Filtrar por familia..." 
                                        id="stats-table-search" 
                                        value={statsSearch}
                                        onInput={(e) => setStatsSearch(e.target.value)}
                                        autoComplete="off"
                                    />
                                </div>
                            </div>
                            <div style={{ overflowX: 'auto', maxHeight: '450px' }}>
                                <table className="stats-table" style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                                    <thead>
                                        <tr style={{ backgroundColor: 'rgba(255,255,255,0.01)' }}>
                                            <th style={{ padding: '12px 24px' }}>Familia Botánica</th>
                                            <th>Fotos Commons</th>
                                            <th>Fotos Locales</th>
                                            <th>Progreso Descarga</th>
                                            <th>Último Escaneo</th>
                                            <th>Acción</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {filteredGlobalStats.length === 0 ? (
                                            <tr>
                                                <td colSpan="6" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>No se encontraron familias.</td>
                                            </tr>
                                        ) : (
                                            filteredGlobalStats.map((name, idx) => {
                                                const info = globalStats[name];
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

                                                return (
                                                    <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                                                        <td style={{ padding: '14px 24px', fontWeight: '500' }}>{name}</td>
                                                        <td>{info.commons_files || 0}</td>
                                                        <td>{info.local_files || 0}</td>
                                                         <td>
                                                            {batchScan.active && batchScan.current_family === name ? (
                                                                <span style={{ fontSize: '11px', color: '#60a5fa', fontStyle: 'italic', display: 'flex', alignItems: 'center', gap: '5px' }}>
                                                                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" style={{ animation: 'spin 1s linear infinite', flexShrink: 0 }}>
                                                                        <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
                                                                    </svg>
                                                                    Escaneando...
                                                                </span>
                                                            ) : !info.scanned ? (
                                                                <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic' }}>Sin escanear</span>
                                                            ) : info.commons_files === 0 ? (
                                                                <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic' }}>Sin archivos</span>
                                                            ) : (
                                                                <div className="progress-bar-container">
                                                                    <div className="progress-bar-bg">
                                                                        <div className="progress-bar-fill" style={{ width: `${info.progress || 0}%` }}></div>
                                                                    </div>
                                                                    <span style={{ fontSize: '11px', width: '35px', textAlign: 'right', display: 'inline-block' }}>
                                                                        {info.progress || 0}%
                                                                    </span>
                                                                </div>
                                                            )}
                                                        </td>
                                                        <td style={{ color: 'var(--text-muted)' }}>{info.last_scan || "-"}</td>
                                                        <td>
                                                            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                                                                <span className={`status-badge ${badgeClass}`}>{badgeText}</span>
                                                                <button 
                                                                    className="btn btn-outline" 
                                                                    style={{ padding: '4px 8px', fontSize: '11px' }}
                                                                    onClick={() => quickJumpToFamily(name)}
                                                                >
                                                                    <i data-lucide="eye" style={{ width: '12px', height: '12px' }}></i>
                                                                </button>
                                                            </div>
                                                        </td>
                                                    </tr>
                                                );
                                            })
                                        )}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                )}
            </main>

            {/* Lightbox Modal */}
            <LightboxModal 
                lightbox={lightbox}
                onClose={() => setLightbox(null)}
                onNavigate={navigateLightbox}
                onToggleFav={toggleAlbumFavorite}
                filteredItems={filteredAlbumItems}
                API_BASE={API_BASE}
                activeFamily={activeFamily}
            />
        </div>
    );
}
