// Copies Swagger UI into the build, so /docs is served from this origin
// instead of a CDN: no third-party script runs on a page that carries the
// user's session. Versioned and scanned with the other npm dependencies.
import { copyFileSync, mkdirSync } from "node:fs"
import { dirname, join } from "node:path"
import { createRequire } from "node:module"
import { fileURLToPath } from "node:url"

const require = createRequire(import.meta.url)
const src = dirname(require.resolve("swagger-ui-dist/package.json"))
const out = join(dirname(fileURLToPath(import.meta.url)), "../../api/static/assets/swagger")

mkdirSync(out, { recursive: true })
for (const file of ["swagger-ui-bundle.js", "swagger-ui.css", "favicon-32x32.png"]) {
  copyFileSync(join(src, file), join(out, file))
}
console.log(`Swagger UI copied to ${out}`)
