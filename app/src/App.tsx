import { useEffect, useMemo, useRef, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { open, save } from '@tauri-apps/plugin-dialog'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  Activity,
  ArrowRightLeft,
  Database,
  FolderOpen,
  Minus,
  RefreshCw,
  Save,
  Search,
  Square,
  X,
} from 'lucide-react'
import './index.css'

const DEFAULT_SUFFIX = 'NicoArnoEvilRaptorFireshineRobbo'

type Page = 'Transfer' | 'Editor' | 'Activity'

type Account = {
  steamId: string
  name: string
  source: string
  avatarUrl?: string | null
}

type InventoryEntry = {
  name: string
  category: string
  value: number
  offset: number
}

type SaveSummary = {
  sourceSteamId: string
  cryptoProfile: string
  encryptedSize: number
  plaintextSize: number
  gvasOffset?: null | number
  inventoryCount: number
}

type WriteResult = {
  outputPath: string
  backupPath?: null | string
}

type Preset = {
  id: string
  title: string
  description: string
  appliesTo: (entry: InventoryEntry) => boolean
  value: (entry: InventoryEntry) => number
}

function inferSteamId(path: string) {
  return path.split(/[\\/]/).pop()?.match(/^(\d{15,20})/)?.[1] ?? ''
}

function defaultOutput(sourcePath: string, targetSteamId: string) {
  if (!sourcePath || !targetSteamId) return ''
  const slash = Math.max(sourcePath.lastIndexOf('\\'), sourcePath.lastIndexOf('/'))
  const dir = slash >= 0 ? sourcePath.slice(0, slash + 1) : ''
  return `${dir}${targetSteamId}.save`
}

function prettyName(name: string) {
  return name
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function nowStamp() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export default function App() {
  const [page, setPage] = useState<Page>('Transfer')
  const [status, setStatus] = useState('READY')
  const [logs, setLogs] = useState<string[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [sourcePath, setSourcePath] = useState('')
  const [sourceSteamId, setSourceSteamId] = useState('')
  const [targetSteamId, setTargetSteamId] = useState('')
  const [outputPath, setOutputPath] = useState('')
  const [partySuffix, setPartySuffix] = useState(DEFAULT_SUFFIX)
  const [rewritePayload, setRewritePayload] = useState(true)
  const [profileInput, setProfileInput] = useState('')
  const [inventory, setInventory] = useState<InventoryEntry[]>([])
  const [summary, setSummary] = useState<SaveSummary | null>(null)
  const [category, setCategory] = useState('All')
  const [search, setSearch] = useState('')
  const [selectedPresets, setSelectedPresets] = useState<string[]>([])
  const [saveFolder, setSaveFolder] = useState('')

  const log = (message: string) => setLogs((current) => [`[${nowStamp()}] ${message}`, ...current])

  const runWindowAction = async (label: string, action: () => Promise<void>) => {
    try {
      await action()
    } catch (error) {
      log(`${label} failed: ${String(error)}`)
    }
  }

  const enrichAccountProfiles = (baseAccounts: Account[]) => {
    baseAccounts.forEach((baseAccount) => {
      invoke<Account>('resolve_account', { input: baseAccount.steamId })
        .then((profile) => {
          setAccounts((current) =>
            current.map((account) =>
              account.steamId === baseAccount.steamId
                ? { ...account, name: profile.name || account.name, avatarUrl: profile.avatarUrl ?? account.avatarUrl }
                : account,
            ),
          )
        })
        .catch(() => {
          // Some private/offline Steam profiles do not expose XML profile data.
        })
    })
  }

  const refreshAccounts = async () => {
    setStatus('SCANNING')
    try {
      const result = await invoke<Account[]>('discover_accounts')
      setAccounts(result)
      enrichAccountProfiles(result)
      log(`Found ${result.length} Steam account candidate(s).`)
      setStatus('READY')
    } catch (error) {
      setStatus('ERROR')
      log(`Account scan failed: ${String(error)}`)
    }
  }

  useEffect(() => {
    refreshAccounts()
    invoke<string | null>('default_save_folder')
      .then((path) => setSaveFolder(path ?? ''))
      .catch(() => setSaveFolder(''))
  }, [])

  const categories = useMemo(() => {
    const counts = new Map<string, number>()
    inventory.forEach((entry) => counts.set(entry.category, (counts.get(entry.category) ?? 0) + 1))
    const preferred = [
      'Presets',
      'All',
      'Currency',
      'Items',
      'Fragments',
      'Jokers',
      'Skins',
      'Mounts',
      'Quests',
      'Music',
      'Map',
      'Stats',
      'Challenges',
      'Levels',
      'Raw Integers',
      'Other',
    ]
    return preferred
      .filter((item) => item === 'Presets' || item === 'All' || counts.has(item))
      .map((item) => ({
        name: item,
        count: item === 'Presets' ? selectedPresets.length : item === 'All' ? inventory.length : counts.get(item)!,
      }))
  }, [inventory, selectedPresets.length])

  const filteredInventory = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return inventory.filter((entry) => {
      const categoryMatch = category === 'All' || category === 'Presets' || entry.category === category
      const searchMatch = !needle || entry.name.toLowerCase().includes(needle) || prettyName(entry.name).toLowerCase().includes(needle)
      return categoryMatch && searchMatch
    })
  }, [category, inventory, search])

  const presets = useMemo<Preset[]>(
    () => [
      {
        id: 'max-money',
        title: 'Max Money',
        description: 'Sets money entries such as gold and souls to 999,999.',
        appliesTo: (entry) => entry.name.startsWith('money'),
        value: () => 999_999,
      },
      {
        id: 'max-items',
        title: 'Max Item Amounts',
        description: 'Sets item and fragment inventory amounts to 999.',
        appliesTo: (entry) => entry.category === 'Items' || entry.category === 'Fragments',
        value: () => 999,
      },
      {
        id: 'unlock-jokers',
        title: 'Unlock Jokers',
        description: 'Sets joker inventory entries to owned.',
        appliesTo: (entry) => entry.category === 'Jokers',
        value: () => 1,
      },
      {
        id: 'unlock-skins',
        title: 'Unlock Skins',
        description: 'Sets skin inventory entries to owned.',
        appliesTo: (entry) => entry.category === 'Skins',
        value: () => 1,
      },
      {
        id: 'unlock-mounts',
        title: 'Unlock Mounts',
        description: 'Sets mount inventory entries to owned.',
        appliesTo: (entry) => entry.category === 'Mounts',
        value: () => 1,
      },
      {
        id: 'unlock-collectibles',
        title: 'Unlock Music And Map',
        description: 'Sets music disc and map entries to owned.',
        appliesTo: (entry) => entry.category === 'Music' || entry.category === 'Map',
        value: () => 1,
      },
      {
        id: 'complete-quests',
        title: 'Complete Quest Flags',
        description: 'Sets quest-like inventory flags to complete.',
        appliesTo: (entry) => entry.category === 'Quests',
        value: () => 1,
      },
    ],
    [],
  )

  const pickSaveFile = async () => {
    const selected = await open({
      multiple: false,
      defaultPath: saveFolder || undefined,
      filters: [{ name: 'Far Far West save', extensions: ['save'] }],
    })
    return typeof selected === 'string' ? selected : ''
  }

  const applySourcePath = (selected: string) => {
    setSourcePath(selected)
    const id = inferSteamId(selected)
    setSourceSteamId(id)
    if (targetSteamId) setOutputPath(defaultOutput(selected, targetSteamId))
    log(`Selected source save: ${selected}`)
    return { selected, id }
  }

  const chooseSource = async () => {
    const selected = await pickSaveFile()
    if (!selected) return
    applySourcePath(selected)
  }

  const chooseOutput = async () => {
    const selected = await save({
      filters: [{ name: 'Far Far West save', extensions: ['save'] }],
      defaultPath: outputPath || defaultOutput(sourcePath, targetSteamId) || 'transferred.save',
    })
    if (selected) setOutputPath(selected)
  }

  const selectAccount = (account: Account) => {
    setTargetSteamId(account.steamId)
    setOutputPath(defaultOutput(sourcePath, account.steamId))
  }

  const resolveAccount = async () => {
    if (!profileInput.trim()) return
    setStatus('RESOLVING')
    try {
      const account = await invoke<Account>('resolve_account', { input: profileInput })
      setAccounts((current) => [account, ...current.filter((item) => item.steamId !== account.steamId)])
      selectAccount(account)
      log(`Resolved Steam profile: ${account.name} (${account.steamId})`)
      setStatus('READY')
    } catch (error) {
      setStatus('ERROR')
      log(`Resolve failed: ${String(error)}`)
    }
  }

  const transfer = async () => {
    if (!sourcePath || !targetSteamId) {
      log('Choose a source save and target SteamID first.')
      return
    }
    const sourceId = sourceSteamId || inferSteamId(sourcePath)
    const out = outputPath || defaultOutput(sourcePath, targetSteamId)
    setStatus('TRANSFERRING')
    try {
      const result = await invoke<WriteResult>('transfer_save', {
        request: {
          sourcePath,
          sourceSteamId: sourceId,
          targetSteamId,
          outputPath: out,
          partySuffix,
          rewritePayload,
        },
      })
      setOutputPath(result.outputPath)
      setStatus('COMPLETE')
      log(`Transferred save written: ${result.outputPath}`)
      if (result.backupPath) log(`Backup created: ${result.backupPath}`)
    } catch (error) {
      setStatus('ERROR')
      log(`Transfer failed: ${String(error)}`)
    }
  }

  const loadEditor = async () => {
    let activePath = sourcePath
    let activeSteamId = sourceSteamId
    if (!activePath) {
      const selected = await pickSaveFile()
      if (!selected) {
        log('Choose a source save before loading the editor.')
        return
      }
      const applied = applySourcePath(selected)
      activePath = applied.selected
      activeSteamId = applied.id
    }
    const sourceId = activeSteamId || inferSteamId(activePath)
    setStatus('LOADING')
    try {
      const saveSummary = await invoke<SaveSummary>('load_save', {
        path: activePath,
        steamId: sourceId,
        partySuffix,
      })
      const rows = await invoke<InventoryEntry[]>('load_inventory', {
        path: activePath,
        steamId: sourceId,
        partySuffix,
      })
      setSummary(saveSummary)
      setInventory(rows)
      setCategory('All')
      setPage('Editor')
      setStatus('LOADED')
      log(`Loaded ${rows.length} editable integer value(s) via ${saveSummary.cryptoProfile}.`)
    } catch (error) {
      setStatus('ERROR')
      log(`Load failed: ${String(error)}`)
    }
  }

  const saveEdited = async () => {
    if (!sourcePath || inventory.length === 0) {
      log('Load a save before writing edits.')
      return
    }
    const selected = await save({
      filters: [{ name: 'Far Far West save', extensions: ['save'] }],
      defaultPath: outputPath || sourcePath,
    })
    if (!selected) return
    setStatus('SAVING')
    try {
      const result = await invoke<WriteResult>('save_inventory', {
        request: {
          sourcePath,
          outputPath: selected,
          steamId: sourceSteamId || inferSteamId(sourcePath),
          partySuffix,
          updates: inventory.map(({ offset, value }) => ({ offset, value })),
        },
      })
      setStatus('SAVED')
      log(`Edited save written: ${result.outputPath}`)
      if (result.backupPath) log(`Backup created: ${result.backupPath}`)
    } catch (error) {
      setStatus('ERROR')
      log(`Save failed: ${String(error)}`)
    }
  }

  const updateInventoryValue = (offset: number, value: string) => {
    const parsed = Number.parseInt(value, 10)
    if (Number.isNaN(parsed)) return
    setInventory((rows) => rows.map((row) => (row.offset === offset ? { ...row, value: parsed } : row)))
  }

  const togglePreset = (id: string) => {
    setSelectedPresets((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]))
  }

  const applySelectedPresets = () => {
    if (inventory.length === 0) {
      log('Load a save before applying presets.')
      return
    }
    const active = presets.filter((preset) => selectedPresets.includes(preset.id))
    if (active.length === 0) {
      log('Select at least one preset first.')
      return
    }
    let changed = 0
    const nextRows = inventory.map((row) => {
        const preset = active.find((item) => item.appliesTo(row))
        if (!preset) return row
        const nextValue = preset.value(row)
        if (nextValue === row.value) return row
        changed += 1
        return { ...row, value: nextValue }
      })
    setInventory(nextRows)
    log(`Applied ${active.length} preset(s) to ${changed} value(s). Save the edited copy to write them.`)
  }

  return (
    <div className="window-shell">
      <div className="window-titlebar" data-tauri-drag-region="true">
        <div className="window-drag-region" data-tauri-drag-region="true">
          <div className="window-brand" data-tauri-drag-region="true">
            <span className="window-mark" data-tauri-drag-region="true">FW</span>
            <span data-tauri-drag-region="true">Far Far West Save Studio</span>
          </div>
        </div>
        <div className="window-controls">
          <button className="window-control" aria-label="Minimize" onClick={() => runWindowAction('Minimize', () => getCurrentWindow().minimize())}>
            <Minus size={14} />
          </button>
          <button className="window-control" aria-label="Maximize" onClick={() => runWindowAction('Maximize', () => getCurrentWindow().toggleMaximize())}>
            <Square size={11} />
          </button>
          <button className="window-control close" aria-label="Close" onClick={() => runWindowAction('Close', () => getCurrentWindow().close())}>
            <X size={15} />
          </button>
        </div>
      </div>
      
      <div className="app">
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-title">FAR FAR WEST</div>
            <div className="brand-subtitle">Save Studio</div>
          </div>
          <nav className="nav">
            <button className={`nav-button ${page === 'Transfer' ? 'active' : ''}`} onClick={() => setPage('Transfer')}>
              <ArrowRightLeft size={16} /> Transfer
            </button>
            <button className={`nav-button ${page === 'Editor' ? 'active' : ''}`} onClick={() => setPage('Editor')}>
              <Database size={16} /> Editor
            </button>
            <button className={`nav-button ${page === 'Activity' ? 'active' : ''}`} onClick={() => setPage('Activity')}>
              <Activity size={16} /> Activity
            </button>
          </nav>
          <div className="sidebar-note">Native Tauri utility. Always creates backups before overwriting files.</div>
        </aside>

        <main className="main">
          <header className="topbar">
            <h1 className="title">{page === 'Editor' ? 'Save Editor' : page}</h1>
            <div className="status-pill">{status}</div>
          </header>

          {page === 'Transfer' && (
            <section className="page transfer-grid">
              <div className="panel panel-pad">
                <h2 className="panel-title">Transfer Save</h2>
                <p className="panel-copy">Migrate a save file to a different Steam account with correct encryption headers.</p>

                <div className="form-grid">
                  <div className="field">
                    <label>Source Save File</label>
                    <input className="input" value={sourcePath} onChange={(e) => setSourcePath(e.target.value)} spellCheck={false} />
                  </div>
                  <button className="button primary" onClick={chooseSource}>
                    <FolderOpen size={15} /> Browse
                  </button>

                  <div className="field">
                    <label>Source SteamID64</label>
                    <input className="input" value={sourceSteamId} onChange={(e) => setSourceSteamId(e.target.value)} spellCheck={false} />
                  </div>
                  <button className="button" onClick={() => setSourceSteamId(inferSteamId(sourcePath))}>
                    Detect
                  </button>

                  <div className="field full">
                    <label>Target SteamID64</label>
                    <input className="input" value={targetSteamId} onChange={(e) => setTargetSteamId(e.target.value)} spellCheck={false} />
                  </div>

                  <div className="field">
                    <label>Output Save Path</label>
                    <input className="input" value={outputPath} onChange={(e) => setOutputPath(e.target.value)} spellCheck={false} />
                  </div>
                  <button className="button" onClick={chooseOutput}>
                    <Save size={15} /> Save As
                  </button>

                  <label className="toggle">
                    <input type="checkbox" checked={rewritePayload} onChange={(e) => setRewritePayload(e.target.checked)} />
                    Rewrite SteamID in decrypted payload
                  </label>

                  <div className="field full">
                    <label>Party Suffix</label>
                    <input className="input" value={partySuffix} onChange={(e) => setPartySuffix(e.target.value)} spellCheck={false} />
                  </div>

                  <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '8px', marginTop: '8px' }}>
                    <button className="button success" style={{ flex: 1 }} onClick={transfer}>
                      Transfer Save
                    </button>
                    <button className="button" style={{ flex: 1 }} onClick={loadEditor}>
                      Load in Editor
                    </button>
                  </div>
                </div>
              </div>

              <div className="panel account-panel">
                <h2 className="panel-title">Target Account</h2>
                <p className="panel-copy">Search or select a local Steam profile.</p>
                
                <div className="resolve-row">
                  <input className="input" placeholder="Steam URL or ID64..." value={profileInput} onChange={(e) => setProfileInput(e.target.value)} spellCheck={false} />
                  <button className="button primary" onClick={resolveAccount}>Resolve</button>
                </div>

                <div className="account-list">
                  <button className="button" style={{ marginBottom: '4px' }} onClick={refreshAccounts}>
                    <RefreshCw size={14} /> Refresh Local Accounts
                  </button>
                  {accounts.map((account) => (
                    <button
                      key={`${account.steamId}-${account.source}`}
                      className={`account-card ${account.steamId === targetSteamId ? 'selected' : ''}`}
                      onClick={() => selectAccount(account)}
                    >
                      {account.avatarUrl ? (
                        <img className="avatar" src={account.avatarUrl} alt="" />
                      ) : (
                        <div className="avatar-fallback">{account.name.slice(0, 1).toUpperCase()}</div>
                      )}
                      <span>
                        <span className="account-name">{account.name}</span>
                        <span className="account-id">{account.steamId}</span>
                      </span>
                    </button>
                  ))}
                  {accounts.length === 0 && <div className="empty" style={{ padding: '20px' }}>No accounts found.</div>}
                </div>
              </div>
            </section>
          )}

          {page === 'Editor' && (
            <EditorPage
              categories={categories}
              category={category}
              setCategory={setCategory}
              search={search}
              setSearch={setSearch}
              presets={presets}
              selectedPresets={selectedPresets}
              togglePreset={togglePreset}
              selectAllPresets={() => setSelectedPresets(presets.map((preset) => preset.id))}
              clearPresets={() => setSelectedPresets([])}
              applySelectedPresets={applySelectedPresets}
              rows={filteredInventory}
              summary={summary}
              loadEditor={loadEditor}
              saveEdited={saveEdited}
              updateInventoryValue={updateInventoryValue}
            />
          )}

          {page === 'Activity' && (
            <section className="page activity">
              <textarea className="log" value={logs.join('\n')} readOnly spellCheck={false} />
            </section>
          )}
        </main>
      </div>
    </div>
  )
}

function EditorPage({
  categories,
  category,
  setCategory,
  search,
  setSearch,
  presets,
  selectedPresets,
  togglePreset,
  selectAllPresets,
  clearPresets,
  applySelectedPresets,
  rows,
  summary,
  loadEditor,
  saveEdited,
  updateInventoryValue,
}: {
  categories: { name: string; count: number }[]
  category: string
  setCategory: (category: string) => void
  search: string
  setSearch: (value: string) => void
  presets: Preset[]
  selectedPresets: string[]
  togglePreset: (id: string) => void
  selectAllPresets: () => void
  clearPresets: () => void
  applySelectedPresets: () => void
  rows: InventoryEntry[]
  summary: SaveSummary | null
  loadEditor: () => void
  saveEdited: () => void
  updateInventoryValue: (offset: number, value: string) => void
}) {
  const showPresets = category === 'Presets'
  const parentRef = useRef<HTMLDivElement>(null)
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 48,
    overscan: 10,
  })

  return (
    <section className="page editor-layout">
      <aside className="panel category-rail">
        <div className="category-title">Categories</div>
        {categories.length === 0 && <div className="empty">No save loaded.</div>}
        {categories.map((item) => (
          <button
            key={item.name}
            className={`category-button ${item.name === category ? 'active' : ''}`}
            onClick={() => setCategory(item.name)}
          >
            <span>{item.name}</span>
            <span style={{ opacity: 0.5, fontSize: '11px' }}>{item.count}</span>
          </button>
        ))}
      </aside>

      <div className="editor-main">
        <div className="panel panel-pad editor-header">
          <div>
            <h2 className="panel-title">Inventory Editor</h2>
            <div className="editor-summary">
              {summary
                ? `${summary.inventoryCount} values • ${summary.cryptoProfile}`
                : 'Load a save to edit game values.'}
            </div>
          </div>
          <button className="button primary" onClick={loadEditor}>Load Save</button>
        </div>

        {showPresets ? (
          <div className="panel preset-panel" style={{ flex: 1, minHeight: 0 }}>
            <div className="preset-heading">
              <div>
                <h2 className="panel-title">Automation Presets</h2>
                <div className="editor-summary">Select presets to batch-update inventory values.</div>
              </div>
              <div className="preset-actions">
                <button className="button primary" onClick={applySelectedPresets}>Apply</button>
                <button className="button" onClick={selectAllPresets}>All</button>
                <button className="button" onClick={clearPresets}>None</button>
              </div>
            </div>
            <div className="preset-list">
              {presets.map((preset) => (
                <label className="preset-card" key={preset.id}>
                  <input type="checkbox" checked={selectedPresets.includes(preset.id)} onChange={() => togglePreset(preset.id)} />
                  <span>
                    <span className="preset-title">{preset.title}</span>
                    <span className="preset-copy">{preset.description}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>
        ) : (
          <>
            <div className="resolve-row" style={{ marginBottom: 0 }}>
              <input
                className="input"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search inventory..."
                spellCheck={false}
              />
              <button className="button" onClick={() => setSearch('')}>
                <Search size={14} />
              </button>
            </div>

            <div className="table-wrap" ref={parentRef}>
              <div className="table-header">
                <div>Field Name</div>
                <div>Category</div>
                <div style={{ textAlign: 'right' }}>Value</div>
              </div>
              {rows.length === 0 ? (
                <div className="empty">No values found.</div>
              ) : (
                <div style={{ height: `${rowVirtualizer.getTotalSize()}px`, position: 'relative' }}>
                  {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                    const row = rows[virtualRow.index]
                    return (
                      <div
                        key={row.offset}
                        className="table-row"
                        style={{
                          position: 'absolute',
                          top: 0,
                          left: 0,
                          width: '100%',
                          transform: `translateY(${virtualRow.start}px)`,
                        }}
                      >
                        <div style={{ overflow: 'hidden' }}>
                          <div className="entry-title" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {prettyName(row.name)}
                          </div>
                          <div className="entry-raw" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {row.name}
                          </div>
                        </div>
                        <div>
                          <span className="category-badge">{row.category}</span>
                        </div>
                        <input
                          className="input value-input"
                          type="number"
                          value={row.value}
                          onChange={(event) => updateInventoryValue(row.offset, event.target.value)}
                        />
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </>
        )}

        <button className="button success" style={{ height: '40px' }} onClick={saveEdited}>
          <Save size={16} /> Save Edits
        </button>
      </div>
    </section>
  )
}
