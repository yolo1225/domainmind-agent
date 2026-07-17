import { getData } from './client'

export interface DomainSummary {
  domain_code: string
  name: string
  status: string
}

export function listDomains() {
  return getData<DomainSummary[]>('/domains')
}

export function validateDomain(domainCode: string) {
  return getData<{ domain_code: string; passed: boolean; issues: Array<{ message: string }> }>(
    `/domains/${domainCode}/validate`,
  )
}
