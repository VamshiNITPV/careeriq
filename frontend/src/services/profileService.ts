import { api } from './apiClient'
import type { PreferencesReplace, Profile, ProfilePersonalUpdate } from '@/types/profile'

/**
 * Profile API.
 *
 * Both mutations return the full profile, so a save is one request and the
 * caller can push the response straight into context — no read-back.
 */
export const profileService = {
  get(): Promise<Profile> {
    return api.get<Profile>('/profile')
  },

  /** Partial update — only the keys present are changed. */
  updatePersonal(changes: ProfilePersonalUpdate): Promise<Profile> {
    return api.patch<Profile>('/profile', changes)
  },

  /**
   * Replaces the preference set wholesale.
   *
   * PUT, not PATCH: these are list fields, and "clear this list" and "leave it
   * alone" would be the same PATCH payload.
   */
  replacePreferences(preferences: PreferencesReplace): Promise<Profile> {
    return api.put<Profile>('/profile/preferences', preferences)
  },
}
