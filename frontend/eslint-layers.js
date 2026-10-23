import path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Folder layering for src/. A folder may import itself and the folders listed
 * for it; everything else points upward and is reported.
 *
 *   app → pages → features/explorer (the '/' screen)
 *     → features/{catalogue, monitoring} → features/pipelines → features/workspace
 *     → features/{readings, account, settings} → features/charts → domain → shared
 *
 * shared is lib/, hooks/, components/, types/ and auth/: generic building blocks
 * that know nothing about features.
 */
const SHARED = ['shared']
const ALLOWED = {
  shared: SHARED,
  domain: SHARED,
  'features/charts': SHARED,
  'features/account': [...SHARED, 'domain'],
  'features/settings': [...SHARED, 'domain'],
  'features/readings': [...SHARED, 'domain', 'features/charts'],
  'features/workspace': [...SHARED, 'domain', 'features/charts'],
  'features/pipelines': [...SHARED, 'domain', 'features/charts', 'features/workspace'],
  'features/monitoring': [...SHARED, 'domain', 'features/charts', 'features/readings', 'features/workspace', 'features/pipelines'],
  'features/catalogue': [...SHARED, 'domain', 'features/charts', 'features/readings', 'features/workspace'],
}
const SCREENS = Object.keys(ALLOWED).filter(layer => layer.startsWith('features/'))
ALLOWED['features/explorer'] = [...SHARED, 'domain', ...SCREENS]
ALLOWED.pages = [...ALLOWED['features/explorer'], 'features/explorer']
ALLOWED.app = [...ALLOWED.pages, 'pages']

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), 'src')

function layerOf(file) {
  const relative = path.relative(SRC, file)
  if (relative.startsWith('..')) return undefined
  const [top, sub] = relative.split(path.sep)
  if (top === 'features') return `features/${sub}`
  if (top === 'app' || relative === 'main.tsx') return 'app'
  if (top === 'pages' || top === 'domain') return top
  if (top === 'Tests') return undefined
  return 'shared'
}

export default {
  rules: {
    'allowed-imports': {
      meta: { type: 'problem', schema: [] },
      create(context) {
        const from = layerOf(context.filename)
        if (!from) return {}
        const check = (node) => {
          const spec = node?.value
          if (typeof spec !== 'string') return
          const target = spec.startsWith('@/') ? path.join(SRC, spec.slice(2))
            : spec.startsWith('.') ? path.resolve(path.dirname(context.filename), spec) : undefined
          const to = target && layerOf(target)
          if (!to || to === from) return
          const allowed = ALLOWED[from]
          if (!allowed) {
            context.report({ node, message: `Add ${from} to eslint-layers.js before it imports other folders.` })
          } else if (!allowed.includes(to)) {
            context.report({ node, message: `${from} may not import ${to}; see the layering in eslint-layers.js.` })
          }
        }
        return {
          ImportDeclaration: (node) => check(node.source),
          ExportNamedDeclaration: (node) => check(node.source),
          ExportAllDeclaration: (node) => check(node.source),
          ImportExpression: (node) => check(node.source),
        }
      },
    },
  },
}
