// Form state helpers shared by New vendor and Resubmit.
import type { EntityType, SubmissionForm } from '../api'

export const EMPTY_FORM: SubmissionForm = {
  legal_name: '', trade_name: '', entity_type: '',
  address: { line1: '', city: '', state: '', pin_code: '' },
  contact_name: '', contact_email: '', gstin: '', pan: '',
  bank: { account_holder_name: '', account_number: '', ifsc: '', bank_name: '' },
}

export function formFromSubmission(s: Record<string, unknown>): SubmissionForm {
  const str = (v: unknown) => (typeof v === 'string' ? v : '')
  const obj = (v: unknown) => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {})
  const a = obj(s.address), b = obj(s.bank)
  return {
    legal_name: str(s.legal_name), trade_name: str(s.trade_name), entity_type: (str(s.entity_type) as EntityType) || '',
    address: { line1: str(a.line1), city: str(a.city), state: str(a.state), pin_code: str(a.pin_code) },
    contact_name: str(s.contact_name), contact_email: str(s.contact_email), gstin: str(s.gstin), pan: str(s.pan),
    bank: { account_holder_name: str(b.account_holder_name), account_number: str(b.account_number),
      ifsc: str(b.ifsc), bank_name: str(b.bank_name) },
  }
}
