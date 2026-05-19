/**
 * discord.ts — Helpers cho Discord asset URLs.
 *
 * Discord User ID là 64-bit BigInt — không được parse bằng Number()
 * (mất chính xác). Dùng BigInt cho mọi tính toán liên quan ID.
 */

/**
 * Build URL Discord default avatar dựa trên user_id.
 *
 * Format mới (sau 2023): index = (user_id >> 22) % 6
 * Format cũ (legacy users): index = discriminator % 5
 *
 * Trả về fallback URL nếu lỗi parse.
 */
export function defaultDiscordAvatar(userId: string | null | undefined): string {
  if (!userId) return 'https://cdn.discordapp.com/embed/avatars/0.png';
  try {
    const id = BigInt(userId);
    const index = Number((id >> 22n) % 6n);
    return `https://cdn.discordapp.com/embed/avatars/${index}.png`;
  } catch {
    return 'https://cdn.discordapp.com/embed/avatars/0.png';
  }
}

/**
 * Build URL Discord user avatar nếu có hash, fallback default.
 */
export function discordAvatarUrl(
  userId: string | null | undefined,
  avatarHash: string | null | undefined,
  size: 64 | 128 | 256 | 512 = 128,
): string {
  if (!userId) return defaultDiscordAvatar(userId);
  if (!avatarHash) return defaultDiscordAvatar(userId);
  // Animated avatars start with "a_"
  const ext = avatarHash.startsWith('a_') ? 'gif' : 'png';
  return `https://cdn.discordapp.com/avatars/${userId}/${avatarHash}.${ext}?size=${size}`;
}
