import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Building2, CheckCircle2, Database, Link2, MapPin, Plus, RefreshCw, Save, Search, ShieldCheck, Store, Tag, Trash2, Upload } from 'lucide-react'
import { bindPackageItem, deletePackageOffer, getPackageTestMessages, importPackageMaterial, listPackageOffers, listPackageVenues, PackageOffer, PackageVenue, savePackageOffer, savePackageVenue, seedKnownPackageCommands, testPackageMatch } from '@/api/packageReplies'
import { getAccountDetails } from '@/api/accounts'
import { getItems } from '@/api/items'
import { useUIStore } from '@/store/uiStore'
import type { Account, Item } from '@/types'

type VenueForm = {
  category: string
  city: string
  area: string
  brand: string
  venue_name: string
  address_note: string
  aliases: string[]
  enabled: boolean
}

type OfferForm = {
  package_name: string
  keywords: string[]
  command_type: 'numeric' | 'group_text'
  command_value: string
  applicability_note: string
  protected: boolean
  enabled: boolean
  sort_order: number
}

const emptyVenue: VenueForm = {
  category: '洗浴',
  city: '',
  area: '',
  brand: '',
  venue_name: '',
  address_note: '',
  aliases: [],
  enabled: true,
}

const emptyOffer: OfferForm = {
  package_name: '',
  keywords: [],
  command_type: 'numeric' as const,
  command_value: '',
  applicability_note: '',
  protected: true,
  enabled: true,
  sort_order: 100,
}

const splitLines = (value: string) => value.split(/[\n,，、]+/).map(item => item.trim()).filter(Boolean)

export function PackageReplies() {
  const { addToast } = useUIStore()
  const [venues, setVenues] = useState<PackageVenue[]>([])
  const [offers, setOffers] = useState<PackageOffer[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [items, setItems] = useState<Item[]>([])
  const [selectedVenueId, setSelectedVenueId] = useState<number | null>(null)
  const [selectedAccount, setSelectedAccount] = useState('')
  const [selectedItemId, setSelectedItemId] = useState('')
  const [venueForm, setVenueForm] = useState<VenueForm>({ ...emptyVenue })
  const [offerForm, setOfferForm] = useState<OfferForm>({ ...emptyOffer })
  const [aliasText, setAliasText] = useState('')
  const [keywordText, setKeywordText] = useState('')
  const [materialText, setMaterialText] = useState('')
  const [testMessage, setTestMessage] = useState('')
  const [testMessages, setTestMessages] = useState<string[]>([])
  const [testResult, setTestResult] = useState('')
  const [loading, setLoading] = useState(false)
  const [venueSearch, setVenueSearch] = useState('')

  const selectedVenue = useMemo(
    () => venues.find(venue => venue.id === selectedVenueId) || null,
    [venues, selectedVenueId],
  )

  const selectedAccountItems = useMemo(
    () => items.filter(item => !selectedAccount || item.cookie_id === selectedAccount),
    [items, selectedAccount],
  )

  const filteredVenues = useMemo(() => {
    const keyword = venueSearch.trim().toLowerCase()
    if (!keyword) return venues
    return venues.filter(venue => [
      venue.city,
      venue.area,
      venue.brand,
      venue.venue_name,
      venue.address_note,
      ...(venue.aliases || []),
    ].filter(Boolean).some(value => String(value).toLowerCase().includes(keyword)))
  }, [venues, venueSearch])

  const venueStats = useMemo(() => ({
    venueCount: venues.length,
    offerCount: venues.reduce((sum, venue) => sum + (venue.offer_count || 0), 0),
    bindingCount: venues.reduce((sum, venue) => sum + (venue.binding_count || 0), 0),
  }), [venues])

  const loadVenues = async () => {
    try {
      setLoading(true)
      const response = await listPackageVenues()
      const list = response.data || []
      setVenues(list)
      if (!selectedVenueId && list.length > 0) {
        selectVenue(list[0])
      }
    } catch {
      addToast({ type: 'error', message: '加载套餐门店失败' })
    } finally {
      setLoading(false)
    }
  }

  const loadOffers = async (venueId: number) => {
    try {
      const response = await listPackageOffers(venueId)
      setOffers(response.data || [])
    } catch {
      setOffers([])
      addToast({ type: 'error', message: '加载套餐失败' })
    }
  }

  const loadAccounts = async () => {
    try {
      const data = await getAccountDetails()
      setAccounts(data)
    } catch {
      setAccounts([])
    }
  }

  const loadItems = async (accountId: string) => {
    if (!accountId) {
      setItems([])
      return
    }
    try {
      const result = await getItems(accountId)
      setItems(result.data || [])
    } catch {
      setItems([])
    }
  }

  useEffect(() => {
    loadVenues()
    loadAccounts()
    getPackageTestMessages().then(response => setTestMessages(response.data || [])).catch(() => setTestMessages([]))
  }, [])

  useEffect(() => {
    if (selectedAccount) loadItems(selectedAccount)
  }, [selectedAccount])

  const selectVenue = (venue: PackageVenue) => {
    setSelectedVenueId(venue.id)
    setVenueForm({
      category: venue.category || '洗浴',
      city: venue.city || '',
      area: venue.area || '',
      brand: venue.brand || '',
      venue_name: venue.venue_name || '',
      address_note: venue.address_note || '',
      aliases: venue.aliases || [],
      enabled: venue.enabled,
    })
    setAliasText((venue.aliases || []).join('\n'))
    setOfferForm({ ...emptyOffer })
    setKeywordText('')
    loadOffers(venue.id)
  }

  const saveVenue = async (event: FormEvent) => {
    event.preventDefault()
    if (!venueForm.city.trim() || !venueForm.brand.trim() || !venueForm.venue_name.trim()) {
      addToast({ type: 'warning', message: '城市、品牌、门店不能为空' })
      return
    }
    const response = await savePackageVenue({
      ...(selectedVenueId ? { id: selectedVenueId } : {}),
      ...venueForm,
      aliases: splitLines(aliasText),
    })
    if (response.success && response.data) {
      addToast({ type: 'success', message: '门店已保存' })
      await loadVenues()
      selectVenue(response.data)
    }
  }

  const saveOffer = async (event: FormEvent) => {
    event.preventDefault()
    if (!selectedVenueId) {
      addToast({ type: 'warning', message: '请先选择门店' })
      return
    }
    if (!offerForm.package_name.trim() || !offerForm.command_value.trim()) {
      addToast({ type: 'warning', message: '套餐名和口令不能为空' })
      return
    }
    const response = await savePackageOffer(selectedVenueId, {
      ...offerForm,
      keywords: splitLines(keywordText),
    })
    if (response.success) {
      addToast({ type: 'success', message: '套餐已保存' })
      setOfferForm({ ...emptyOffer })
      setKeywordText('')
      await loadOffers(selectedVenueId)
      await loadVenues()
    }
  }

  const importMaterial = async () => {
    if (!materialText.trim()) {
      addToast({ type: 'warning', message: '请先粘贴团口令素材' })
      return
    }
    const response = await importPackageMaterial(selectedVenueId, materialText)
    const importedCount = response.data?.imported?.length || 0
    const candidateCount = response.data?.candidates?.length || 0
    addToast({ type: importedCount > 0 ? 'success' : 'warning', message: `导入 ${importedCount} 条，待确认 ${candidateCount} 条` })
    if (selectedVenueId) {
      await loadOffers(selectedVenueId)
      await loadVenues()
    }
  }

  const seedKnown = async () => {
    const response = await seedKnownPackageCommands()
    if (response.success) {
      addToast({ type: 'success', message: `已导入已知数字口令：${response.data?.offers_created || 0} 条新增` })
      await loadVenues()
      if (selectedVenueId) await loadOffers(selectedVenueId)
    }
  }

  const bindItem = async () => {
    if (!selectedVenueId || !selectedAccount || !selectedItemId) {
      addToast({ type: 'warning', message: '请选择账号、商品和门店' })
      return
    }
    const response = await bindPackageItem({ account_id: selectedAccount, item_id: selectedItemId, venue_id: selectedVenueId, protected: true })
    if (response.success) {
      addToast({ type: 'success', message: '商品已绑定套餐门店' })
      await loadVenues()
    }
  }

  const runTest = async () => {
    if (!selectedAccount || !testMessage.trim()) {
      addToast({ type: 'warning', message: '请选择账号并填写买家消息' })
      return
    }
    const response = await testPackageMatch({ account_id: selectedAccount, item_id: selectedItemId || undefined, message: testMessage })
    setTestResult(response.data?.reply || (response.data?.need_clarification ? '低置信，需要追问买家确认套餐/门店。' : '未匹配到套餐。'))
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="page-title">套餐回复</h1>
          <p className="page-description">门店素材、套餐口令、商品绑定和买家消息匹配</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={loadVenues} className="btn-ios-secondary" disabled={loading}>
            <RefreshCw className="h-4 w-4" />刷新
          </button>
          <button onClick={seedKnown} className="btn-ios-primary">
            <ShieldCheck className="h-4 w-4" />导入已知口令
          </button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <div className="stat-card">
          <div className="rounded-md bg-blue-50 p-2 text-blue-600 dark:bg-blue-900/30 dark:text-blue-300">
            <Store className="h-5 w-5" />
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">门店</div>
            <div className="text-xl font-semibold text-slate-900 dark:text-slate-100">{venueStats.venueCount}</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="rounded-md bg-emerald-50 p-2 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-300">
            <Tag className="h-5 w-5" />
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">套餐</div>
            <div className="text-xl font-semibold text-slate-900 dark:text-slate-100">{venueStats.offerCount}</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="rounded-md bg-amber-50 p-2 text-amber-600 dark:bg-amber-900/30 dark:text-amber-300">
            <Link2 className="h-5 w-5" />
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">商品绑定</div>
            <div className="text-xl font-semibold text-slate-900 dark:text-slate-100">{venueStats.bindingCount}</div>
          </div>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <aside className="vben-card xl:sticky xl:top-4 xl:self-start">
          <div className="vben-card-header">
            <h2 className="vben-card-title"><Database className="h-4 w-4" />门店</h2>
            <span className="badge-gray">{filteredVenues.length}</span>
          </div>
          <div className="border-b border-slate-100 p-4 dark:border-slate-700">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                className="input-ios pl-9"
                placeholder="搜索城市、品牌、门店"
                value={venueSearch}
                onChange={e => setVenueSearch(e.target.value)}
              />
            </div>
          </div>
          <div className="max-h-[calc(100vh-330px)] min-h-[360px] space-y-2 overflow-auto p-3">
            {filteredVenues.map(venue => {
              const selected = venue.id === selectedVenueId
              return (
              <button
                key={venue.id}
                onClick={() => selectVenue(venue)}
                className={`w-full rounded-md border px-3 py-3 text-left text-sm transition-colors ${selected ? 'border-blue-400 bg-blue-50 text-blue-950 shadow-sm dark:border-blue-500/70 dark:bg-blue-950/40 dark:text-blue-100' : 'border-slate-100 bg-white hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50 dark:hover:bg-slate-700/70'}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{venue.city} · {venue.venue_name}</div>
                    <div className="mt-1 flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
                      <MapPin className="h-3.5 w-3.5" />
                      <span className="truncate">{venue.area || venue.address_note || venue.brand}</span>
                    </div>
                  </div>
                  {selected && <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-blue-500" />}
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <span className="badge-gray">{venue.brand || '未填品牌'}</span>
                  <span className="badge-info">套餐 {venue.offer_count || 0}</span>
                  <span className="badge-success">绑定 {venue.binding_count || 0}</span>
                </div>
              </button>
            )})}
            {!loading && filteredVenues.length === 0 && <div className="py-10 text-center text-sm text-slate-500 dark:text-slate-400">暂无匹配门店</div>}
          </div>
        </aside>

        <div className="space-y-5">
          <section className="vben-card overflow-hidden">
            <div className="vben-card-header">
              <div>
                <h2 className="vben-card-title"><Building2 className="h-4 w-4" />门店资料</h2>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {selectedVenue ? `${selectedVenue.city} · ${selectedVenue.venue_name}` : '选择左侧门店后编辑'}
                </div>
              </div>
              <label className="switch-ios">
                <input type="checkbox" checked={venueForm.enabled} onChange={e => setVenueForm({ ...venueForm, enabled: e.target.checked })} />
                <span className="switch-slider" />
              </label>
            </div>
            <div className="vben-card-body">
              <form onSubmit={saveVenue} className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                <div className="input-group">
                  <label className="input-label">城市</label>
                  <input className="input-ios" placeholder="上海" value={venueForm.city} onChange={e => setVenueForm({ ...venueForm, city: e.target.value })} />
                </div>
                <div className="input-group">
                  <label className="input-label">区域/商圈</label>
                  <input className="input-ios" placeholder="五角场" value={venueForm.area} onChange={e => setVenueForm({ ...venueForm, area: e.target.value })} />
                </div>
                <div className="input-group">
                  <label className="input-label">品牌</label>
                  <input className="input-ios" placeholder="水裹" value={venueForm.brand} onChange={e => setVenueForm({ ...venueForm, brand: e.target.value })} />
                </div>
                <div className="input-group md:col-span-2">
                  <label className="input-label">门店名称</label>
                  <input className="input-ios" placeholder="水裹汤泉生活五角场店" value={venueForm.venue_name} onChange={e => setVenueForm({ ...venueForm, venue_name: e.target.value })} />
                </div>
                <div className="input-group">
                  <label className="input-label">类目</label>
                  <input className="input-ios" placeholder="洗浴" value={venueForm.category} onChange={e => setVenueForm({ ...venueForm, category: e.target.value })} />
                </div>
                <div className="input-group md:col-span-2 xl:col-span-1">
                  <label className="input-label">地址备注</label>
                  <input className="input-ios" placeholder="上海五角场店" value={venueForm.address_note} onChange={e => setVenueForm({ ...venueForm, address_note: e.target.value })} />
                </div>
                <div className="input-group md:col-span-2">
                  <label className="input-label">别名</label>
                  <textarea className="input-ios min-h-24 resize-y" placeholder="水裹汤泉&#10;五角场店" value={aliasText} onChange={e => setAliasText(e.target.value)} />
                </div>
                <div className="flex items-end justify-end md:col-span-2 xl:col-span-1">
                  <button className="btn-ios-primary w-full md:w-auto">
                    <Save className="h-4 w-4" />保存门店
                  </button>
                </div>
              </form>
            </div>
          </section>

          <section className="vben-card">
            <div className="vben-card-header">
              <h2 className="vben-card-title"><Upload className="h-4 w-4" />素材导入</h2>
              <span className="text-xs text-slate-500 dark:text-slate-400">{selectedVenue ? selectedVenue.venue_name : '未选择门店'}</span>
            </div>
            <div className="vben-card-body">
              <textarea className="input-ios min-h-36 resize-y" placeholder="粘贴一个或多个团口令素材；系统只保存套餐名和口令。" value={materialText} onChange={e => setMaterialText(e.target.value)} />
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <div className="text-xs text-slate-500 dark:text-slate-400">会保留完整团口令，已保护套餐不会被覆盖。</div>
                <button onClick={importMaterial} className="btn-ios-secondary">
                  <Upload className="h-4 w-4" />导入到当前门店
                </button>
              </div>
            </div>
          </section>

          <section className="vben-card">
            <div className="vben-card-header">
              <div>
                <h2 className="vben-card-title"><Plus className="h-4 w-4" />套餐配置</h2>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {selectedVenue ? `${selectedVenue.city} ${selectedVenue.venue_name}` : '未选择门店'}
                </div>
              </div>
              <span className="badge-info">{offers.length} 条</span>
            </div>
            <div className="vben-card-body space-y-5">
              <form onSubmit={saveOffer} className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <div className="input-group md:col-span-2 xl:col-span-4">
                  <label className="input-label">套餐名</label>
                  <input className="input-ios" placeholder="水裹·汤泉【榴莲自由】工作日16小时或周末节假日8小时门票" value={offerForm.package_name} onChange={e => setOfferForm({ ...offerForm, package_name: e.target.value })} />
                </div>
                <div className="input-group">
                  <label className="input-label">口令类型</label>
                  <select className="input-ios" value={offerForm.command_type} onChange={e => setOfferForm({ ...offerForm, command_type: e.target.value as 'numeric' | 'group_text' })}>
                    <option value="numeric">数字口令</option>
                    <option value="group_text">完整团口令</option>
                  </select>
                </div>
                <div className="input-group">
                  <label className="input-label">排序</label>
                  <input className="input-ios" placeholder="100" type="number" value={offerForm.sort_order} onChange={e => setOfferForm({ ...offerForm, sort_order: Number(e.target.value) })} />
                </div>
                <label className="checkbox-label mt-7">
                  <input className="checkbox-ios" type="checkbox" checked={offerForm.protected} onChange={e => setOfferForm({ ...offerForm, protected: e.target.checked })} />
                  保护套餐
                </label>
                <label className="checkbox-label mt-7">
                  <input className="checkbox-ios" type="checkbox" checked={offerForm.enabled} onChange={e => setOfferForm({ ...offerForm, enabled: e.target.checked })} />
                  启用
                </label>
                <div className="input-group md:col-span-2">
                  <label className="input-label">口令</label>
                  <textarea className="input-ios min-h-24 resize-y" placeholder="数字口令或完整团口令" value={offerForm.command_value} onChange={e => setOfferForm({ ...offerForm, command_value: e.target.value })} />
                </div>
                <div className="input-group md:col-span-2">
                  <label className="input-label">匹配关键词</label>
                  <textarea className="input-ios min-h-24 resize-y" placeholder="每行一个关键词" value={keywordText} onChange={e => setKeywordText(e.target.value)} />
                </div>
                <div className="flex justify-end md:col-span-2 xl:col-span-4">
                  <button className="btn-ios-primary">
                    <Save className="h-4 w-4" />保存套餐
                  </button>
                </div>
              </form>

              <div className="table-ios-container rounded-lg border border-slate-100 dark:border-slate-700">
                <table className="table-ios min-w-[760px]">
                  <thead>
                    <tr><th>套餐</th><th>口令</th><th>保护</th><th className="w-20">操作</th></tr>
                  </thead>
                  <tbody>
                    {offers.map(offer => (
                      <tr key={offer.id}>
                        <td>
                          <div className="max-w-2xl font-medium text-slate-900 dark:text-slate-100">{offer.package_name}</div>
                          {offer.keywords?.length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1">
                              {offer.keywords.slice(0, 4).map(keyword => <span key={keyword} className="badge-gray">{keyword}</span>)}
                            </div>
                          )}
                        </td>
                        <td className="font-mono text-xs">{offer.command_type === 'numeric' ? offer.command_value : <span className="badge-primary">完整团口令</span>}</td>
                        <td>{offer.protected ? <span className="badge-success"><CheckCircle2 className="mr-1 h-3.5 w-3.5" />已保护</span> : <span className="badge-gray">普通</span>}</td>
                        <td>
                          <button onClick={() => deletePackageOffer(offer.id).then(() => { if (selectedVenueId) void loadOffers(selectedVenueId) })} className="table-action-btn text-red-600 hover:text-red-700 dark:text-red-400" title="删除">
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {offers.length === 0 && (
                      <tr>
                        <td colSpan={4} className="py-10 text-center text-slate-500 dark:text-slate-400">当前门店暂无套餐</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <section className="vben-card">
            <div className="vben-card-header">
              <h2 className="vben-card-title"><Link2 className="h-4 w-4" />商品绑定与测试</h2>
              <span className="text-xs text-slate-500 dark:text-slate-400">{selectedVenue ? selectedVenue.venue_name : '未选择门店'}</span>
            </div>
            <div className="vben-card-body space-y-4">
              <div className="grid gap-3 md:grid-cols-[220px_minmax(0,1fr)_auto]">
                <select className="input-ios" value={selectedAccount} onChange={e => setSelectedAccount(e.target.value)}>
                  <option value="">选择账号</option>
                  {accounts.map(account => <option key={account.id} value={account.id}>{account.remark || account.username || account.id}</option>)}
                </select>
                <select className="input-ios" value={selectedItemId} onChange={e => setSelectedItemId(e.target.value)}>
                  <option value="">选择商品</option>
                  {selectedAccountItems.map(item => <option key={item.item_id} value={item.item_id}>{item.item_id} · {item.title || item.item_title}</option>)}
                </select>
                <button onClick={bindItem} className="btn-ios-success whitespace-nowrap">
                  <Link2 className="h-4 w-4" />绑定当前门店
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                {testMessages.slice(0, 8).map(message => (
                  <button key={message} onClick={() => setTestMessage(message)} className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-blue-950/30 dark:hover:text-blue-200">{message}</button>
                ))}
              </div>
              <div className="grid gap-3 md:grid-cols-[1fr_auto]">
                <input className="input-ios" placeholder="输入买家消息测试匹配" value={testMessage} onChange={e => setTestMessage(e.target.value)} />
                <button onClick={runTest} className="btn-ios-primary">
                  <Search className="h-4 w-4" />测试
                </button>
              </div>
              {testResult && (
                <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md border border-slate-100 bg-slate-50 p-3 text-sm leading-6 text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100">
                  {testResult}
                </pre>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
