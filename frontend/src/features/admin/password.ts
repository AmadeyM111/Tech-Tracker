// One-time password generator (FR-55, FR-65, OI-108): the client chooses the
// password and shows it to the administrator once; the server never returns it.

// No look-alike characters (0/O/o, 1/l/I) because the password is read off a
// screen. 56 symbols x 20 positions is about 116 bits (20 * log2(56)).
const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789";
const LENGTH = 20;
// Largest multiple of the alphabet size that fits in a byte: bytes at or above
// it are discarded (rejection sampling), so every symbol is equally likely.
const LIMIT = 256 - (256 % ALPHABET.length);

/**
 * Random password from crypto.getRandomValues. Letters and digits only, 20
 * symbols: passes the length rule and cannot hit the list of common passwords
 * (nothing in it is 20 random symbols long).
 */
export function generateOneTimePassword(): string {
  let out = "";
  const bytes = new Uint8Array(LENGTH * 2);
  while (out.length < LENGTH) {
    globalThis.crypto.getRandomValues(bytes);
    for (const b of bytes) {
      if (b < LIMIT) {
        out += ALPHABET.charAt(b % ALPHABET.length);
        if (out.length === LENGTH) break;
      }
    }
  }
  return out;
}
