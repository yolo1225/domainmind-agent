import { getData } from './client'

export function listDomains() {
  return getData<Array<{ domain_code: string; name: string; status: string }>>('/domains')
}

export function validateDomain(domainCode: string) {
  return getData<{ domain_code: string; passed: boolean; issues: Array<{ message: string }> }>(
    `/domains/${domainCode}/validate`,
  )
}
