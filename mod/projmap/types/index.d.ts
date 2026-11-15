export type MapIssue = {
  n: number
  plain: string
  stage: string
  kind: 'attention' | 'moving' | 'start' | 'wait'
  note: string
  hint: string
  touches: string[]
  basis: 'merged' | 'open' | 'predicted' | 'none'
  affects: string[]
  url: string
}

export type MapSummary = {
  title: string
  generated: string
  issues: MapIssue[]
  merged: number
  drift: string[]
  caps: string[]
}

export type MapState = {
  status: 'loading' | 'ready' | 'none' | 'failed'
  problem: string
  summary: MapSummary | null
}

declare module 'claude-code' {
  interface PluginState {
    projmap: { map: Shaped<MapState> }
  }
}
