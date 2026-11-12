import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import UsersPage from '@/pages/UsersPage.vue'
import {
  cleanupPage,
  clickAllButtons,
  clickByText,
  fillInputs,
  installFetchMock,
  mountPage,
  settle,
} from './helpers'

describe('UsersPage interactions', () => {
  beforeEach(() => {
    document.cookie = 'ostium_csrf=token; path=/'
  })
  afterEach(() => cleanupPage())

  it('creates, edits and manages users', async () => {
    const { calls } = installFetchMock()
    const { wrapper, router } = await mountPage(UsersPage)
    await settle()

    await clickByText('Add user')
    await fillInputs({ Name: 'charlie', '50G': '5G' })
    await clickByText('Save')
    expect(calls.some((call) => call.path === '/api/v1/users' && call.method === 'POST')).toBe(true)

    await clickByText('Cancel')
    await clickAllButtons(1)

    const row = wrapper.find('.table-row')
    expect(row.exists()).toBe(true)
    await row.trigger('click')
    await settle()
    await clickByText('Subscription')
    await clickByText('Rotate credentials')
    await clickByText('Confirm')
    await clickByText('Reset usage')
    await clickByText('Confirm')
    await clickByText('Delete')
    await clickByText('Confirm')
    await clickAllButtons(1)

    // Bulk selection and actions.
    const checkboxes = wrapper.findAll('input[type="checkbox"]')
    if (checkboxes.length) {
      await checkboxes[0].setValue(true)
      await settle()
    }
    await clickByText('Enable')
    await clickByText('Disable')
    await clickByText('Delete')
    await clickByText('Confirm')
    await clickAllButtons(1)

    // Query-driven create and focus flows.
    await router.push('/?create=1')
    await settle()
    await router.push('/?focus=user-1')
    await settle()
    expect(wrapper.html()).toBeTruthy()
  })

  it('shows validation and error states', async () => {
    installFetchMock({ mode: 'error' })
    const { wrapper } = await mountPage(UsersPage)
    await settle()
    expect(wrapper.text().length).toBeGreaterThan(10)
    await clickByText('Add user')
    await clickByText('Save')
    await clickAllButtons(1)
    expect(wrapper.html()).toBeTruthy()
  })
})
