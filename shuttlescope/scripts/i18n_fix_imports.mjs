#!/usr/bin/env node
// 壊れた multiline import を修復する:
// `import {\nimport { useTranslation } from 'react-i18next'\n   Foo, ...`
// → `import { useTranslation } from 'react-i18next'\nimport {\n   Foo, ...`
import fs from 'node:fs'
import path from 'node:path'

const files = fs.readFileSync(process.argv[2], 'utf8').split('\n').filter(Boolean)

let fixed = 0
for (const rel of files) {
  const abs = path.join(process.cwd(), rel)
  let src = fs.readFileSync(abs, 'utf8')
  const before = src
  // Match: `import {\n` followed by `import { useTranslation } from 'react-i18next'\n`
  src = src.replace(
    /(import\s*\{)(\s*\r?\n)(import \{ useTranslation \} from 'react-i18next'\r?\n)/g,
    (_m, a, ws, inj) => `${inj}${a}${ws}`
  )
  if (src !== before) {
    fs.writeFileSync(abs, src, 'utf8')
    fixed++
  }
}
console.log(`Fixed: ${fixed}`)
