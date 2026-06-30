import { FormEvent, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Database, Link2, Plus, RefreshCw, Save, Search, ShieldCheck, Trash2, Upload } from 'lucide-react'
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

  const selectedVenue = useMemo(
    () => venues.find(venue => venue.id === selectedVenueId) || null,
    [venues, selectedVenueId],
  )

  const selectedAccountItems = useMemo(
    () => items.filter(item => !selectedAccount || item.cookie_id === selectedAccount),
    [items, selectedAccount],
  )

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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">套餐回复</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">配置门店、套餐口令、商品绑定和买家消息匹配</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={loadVenues} className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-100 dark:hover:bg-slate-800">
            <RefreshCw className="h-4 w-4" />刷新
          </button>
          <button onClick={seedKnown} className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm text-white hover:bg-emerald-700">
            <ShieldCheck className="h-4 w-4" />导入已知口令
          </button>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <section className="rounded-md border bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-100">
            <Database className="h-4 w-4" />门店
          </div>
          <div className="max-h-[540px] space-y-2 overflow-auto">
            {venues.map(venue => (
              <button
                key={venue.id}
                onClick={() => selectVenue(venue)}
                className={`w-full rounded-md border px-3 py-2 text-left text-sm ${venue.id === selectedVenueId ? 'border-blue-500 bg-blue-50 text-blue-900 dark:bg-blue-950/40 dark:text-blue-100' : 'border-slate-200 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800'}`}
              >
                <div className="font-medium">{venue.city} · {venue.venue_name}</div>
                <div className="mt-1 text-xs text-slate-500">{venue.brand} / 套餐 {venue.offer_count || 0} / 绑定 {venue.binding_count || 0}</div>
              </button>
            ))}
            {!loading && venues.length === 0 && <div className="py-8 text-center text-sm text-slate-500">暂无门店</div>}
          </div>
        </section>

        <div className="space-y-5">
          <section className="rounded-md border bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
            <form onSubmit={saveVenue} className="grid gap-3 md:grid-cols-2">
              <input className="rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder="城市" value={venueForm.city} onChange={e => setVenueForm({ ...venueForm, city: e.target.value })} />
              <input className="rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder="区域/商圈" value={venueForm.area} onChange={e => setVenueForm({ ...venueForm, area: e.target.value })} />
              <input className="rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder="品牌" value={venueForm.brand} onChange={e => setVenueForm({ ...venueForm, brand: e.target.value })} />
              <input className="rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder="门店名称" value={venueForm.venue_name} onChange={e => setVenueForm({ ...venueForm, venue_name: e.target.value })} />
              <input className="rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder="地址备注" value={venueForm.address_note} onChange={e => setVenueForm({ ...venueForm, address_note: e.target.value })} />
              <input className="rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder="类目" value={venueForm.category} onChange={e => setVenueForm({ ...venueForm, category: e.target.value })} />
              <textarea className="md:col-span-2 min-h-20 rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder="别名，每行一个，例如 九号汤泉 / 四惠店" value={aliasText} onChange={e => setAliasText(e.target.value)} />
              <button className="inline-flex w-fit items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700">
                <Save className="h-4 w-4" />保存门店
              </button>
            </form>
          </section>

          <section className="rounded-md border bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-100">
              <Upload className="h-4 w-4" />素材导入
            </div>
            <textarea className="min-h-36 w-full rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder="粘贴一个或多个团口令素材；会忽略价格和下单链接，只保存套餐名和口令。" value={materialText} onChange={e => setMaterialText(e.target.value)} />
            <button onClick={importMaterial} className="mt-3 inline-flex items-center gap-2 rounded-md bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900">
              <Upload className="h-4 w-4" />导入到当前门店
            </button>
          </section>

          <section className="rounded-md border bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-100">
                <Plus className="h-4 w-4" />套餐
              </div>
              <div className="text-xs text-slate-500">{selectedVenue ? `${selectedVenue.city} ${selectedVenue.venue_name}` : '未选择门店'}</div>
            </div>
            <form onSubmit={saveOffer} className="grid gap-3 md:grid-cols-2">
              <input className="md:col-span-2 rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder="套餐名" value={offerForm.package_name} onChange={e => setOfferForm({ ...offerForm, package_name: e.target.value })} />
              <select className="rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" value={offerForm.command_type} onChange={e => setOfferForm({ ...offerForm, command_type: e.target.value as 'numeric' | 'group_text' })}>
                <option value="numeric">数字口令</option>
                <option value="group_text">完整团口令</option>
              </select>
              <input className="rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder="排序" type="number" value={offerForm.sort_order} onChange={e => setOfferForm({ ...offerForm, sort_order: Number(e.target.value) })} />
              <textarea className="md:col-span-2 min-h-20 rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder="数字口令或完整团口令" value={offerForm.command_value} onChange={e => setOfferForm({ ...offerForm, command_value: e.target.value })} />
              <textarea className="md:col-span-2 min-h-20 rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder="匹配关键词，每行一个" value={keywordText} onChange={e => setKeywordText(e.target.value)} />
              <button className="inline-flex w-fit items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700">
                <Save className="h-4 w-4" />保存套餐
              </button>
            </form>

            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="text-left text-slate-500">
                  <tr><th className="py-2 pr-3">套餐</th><th className="py-2 pr-3">口令</th><th className="py-2 pr-3">保护</th><th className="py-2 pr-3">操作</th></tr>
                </thead>
                <tbody>
                  {offers.map(offer => (
                    <tr key={offer.id} className="border-t dark:border-slate-700">
                      <td className="max-w-lg py-2 pr-3">{offer.package_name}</td>
                      <td className="py-2 pr-3 font-mono text-xs">{offer.command_type === 'numeric' ? offer.command_value : '完整团口令'}</td>
                      <td className="py-2 pr-3">{offer.protected ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : '-'}</td>
                      <td className="py-2 pr-3">
                        <button onClick={() => deletePackageOffer(offer.id).then(() => { if (selectedVenueId) void loadOffers(selectedVenueId) })} className="rounded-md p-2 text-red-600 hover:bg-red-50" title="删除">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="rounded-md border bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-100">
              <Link2 className="h-4 w-4" />商品绑定与测试
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <select className="rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" value={selectedAccount} onChange={e => setSelectedAccount(e.target.value)}>
                <option value="">选择账号</option>
                {accounts.map(account => <option key={account.id} value={account.id}>{account.remark || account.username || account.id}</option>)}
              </select>
              <select className="rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" value={selectedItemId} onChange={e => setSelectedItemId(e.target.value)}>
                <option value="">选择商品</option>
                {selectedAccountItems.map(item => <option key={item.item_id} value={item.item_id}>{item.item_id} · {item.title || item.item_title}</option>)}
              </select>
              <button onClick={bindItem} className="inline-flex items-center justify-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm text-white hover:bg-emerald-700">
                <Link2 className="h-4 w-4" />绑定当前门店
              </button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {testMessages.slice(0, 8).map(message => (
                <button key={message} onClick={() => setTestMessage(message)} className="rounded-md border px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">{message}</button>
              ))}
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-[1fr_auto]">
              <input className="rounded-md border px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder="输入买家消息测试匹配" value={testMessage} onChange={e => setTestMessage(e.target.value)} />
              <button onClick={runTest} className="inline-flex items-center justify-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700">
                <Search className="h-4 w-4" />测试
              </button>
            </div>
            {testResult && (
              <pre className="mt-3 whitespace-pre-wrap rounded-md bg-slate-100 p-3 text-sm text-slate-800 dark:bg-slate-950 dark:text-slate-100">
                {testResult}
              </pre>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
