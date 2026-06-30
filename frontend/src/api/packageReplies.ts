import { get, post, del } from '@/utils/request'
import type { ApiResponse } from '@/types'

const PREFIX = '/api/v1/package-replies'

export interface PackageVenue {
  id: number
  owner_id?: number | null
  category: string
  city: string
  area: string
  brand: string
  venue_name: string
  address_note: string
  aliases: string[]
  enabled: boolean
  offer_count?: number
  binding_count?: number
}

export interface PackageOffer {
  id: number
  venue_id: number
  package_name: string
  keywords: string[]
  command_type: 'numeric' | 'group_text'
  command_value: string
  source_text?: string
  applicability_note?: string
  protected: boolean
  enabled: boolean
  sort_order: number
}

export interface MaterialImportResult {
  imported: PackageOffer[]
  candidates: number[]
  parsed?: Partial<PackageOffer>[]
}

export interface PackageMatchResult {
  matched: boolean
  need_clarification: boolean
  confidence: number
  reason: string
  venue?: PackageVenue | null
  offer?: PackageOffer | null
  reply: string
}

export const listPackageVenues = () => get<ApiResponse<PackageVenue[]>>(`${PREFIX}/venues`)

export const savePackageVenue = (payload: Partial<PackageVenue>) =>
  post<ApiResponse<PackageVenue>>(`${PREFIX}/venues`, payload)

export const listPackageOffers = (venueId: number) =>
  get<ApiResponse<PackageOffer[]>>(`${PREFIX}/venues/${venueId}/offers`)

export const savePackageOffer = (venueId: number, payload: Partial<PackageOffer>) =>
  post<ApiResponse<PackageOffer>>(`${PREFIX}/venues/${venueId}/offers`, payload)

export const deletePackageOffer = (offerId: number) =>
  del<ApiResponse>(`${PREFIX}/offers/${offerId}`)

export const importPackageMaterial = (venueId: number | null, rawText: string) =>
  post<ApiResponse<MaterialImportResult>>(`${PREFIX}/materials/import`, { venue_id: venueId, raw_text: rawText })

export const bindPackageItem = (payload: { account_id: string; item_id: string; venue_id: number; protected?: boolean }) =>
  post<ApiResponse<{ id: number }>>(`${PREFIX}/bindings`, payload)

export const seedKnownPackageCommands = () =>
  post<ApiResponse<Record<string, number>>>(`${PREFIX}/seed-known?include_protected_bindings=true`)

export const testPackageMatch = (payload: { account_id: string; item_id?: string; message: string }) =>
  post<ApiResponse<PackageMatchResult>>(`${PREFIX}/test-match`, payload)

export const getPackageTestMessages = () =>
  get<ApiResponse<string[]>>(`${PREFIX}/test-messages`)
