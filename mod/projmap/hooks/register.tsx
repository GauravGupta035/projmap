import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { MapIssue, MapState, MapSummary } from '../types'

const PANE = 'project-map'
const TITLE = 'Project map'
// Where `projmap serve` puts the full map by default.
const FULL_MAP = 'http://localhost:4400'
const EMPTY: MapState = { status: 'loading', problem: '', summary: null }
const map = atom({ plugin: 'projmap', key: 'map' } as const, EMPTY, {
  shape: 'map-1',
})

const SECTIONS: { kind: MapIssue['kind']; title: string }[] = [
  { kind: 'attention', title: 'Waiting on a person' },
  { kind: 'moving', title: 'Moving now' },
  { kind: 'start', title: 'Can start' },
  { kind: 'wait', title: 'Waiting on another issue' },
]

// The app may not have the login shell's PATH, so a miss is tried again through it.
async function summarise($: EngineInterface) {
  const tries = [
    ['projmap', 'summary'],
    ['/bin/zsh', '-lc', 'projmap summary'],
  ]
  let last = 'projmap did not run'

  for (const argv of tries) {
    try {
      const ran = await $.process.run(argv, { timeoutMs: 120000 })

      if (ran.exitCode === 0) {
        return { summary: JSON.parse(ran.stdout) as MapSummary, problem: '' }
      }

      last = ran.stderr.trim() || last

      if (last.startsWith('projmap:')) {
        break
      }
    } catch (error) {
      last = String(error)
    }
  }

  return { summary: null, problem: last }
}

async function load($: EngineInterface) {
  await update($, map, old => ({ ...old, status: 'loading' as const }))
  const { summary, problem } = await summarise($)
  const hasNoMap = problem.includes('no projmap.json') || problem.includes('not inside a git')

  await update($, map, old =>
    summary
      ? { status: 'ready' as const, problem: '', summary }
      : { status: hasNoMap ? ('none' as const) : ('failed' as const), problem, summary: old.summary },
  )
}

function touchLine(issue: MapIssue) {
  if (issue.basis === 'none') {
    return 'touches: not known yet'
  }

  const how = issue.basis === 'predicted' ? ' (predicted)' : ''
  const felt = issue.affects.length ? `, then felt by ${issue.affects.join(', ')}` : ''

  return `touches ${issue.touches.join(', ')}${how}${felt}`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'map',
      description: 'Show the project map pane and refresh it',
    })
    void $.ui.open({ id: PANE, title: TITLE })
    $.clock.after(200, () => load($))
    $.clock.every(300000, () => load($))

    return next(e)
  })

  on('command.run', { command: 'map' }, async $ => {
    await $.ui.open({ id: PANE, title: TITLE })
    await load($)

    return { text: 'Project map refreshed.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Link, Text } = $.ui.resolve(e)
    const state = await read($, map)
    const summary = state.summary

    if (!summary) {
      return (
        <Box flexDirection="column">
          {state.status === 'loading' && <Text dimColor>Reading the repo and GitHub.</Text>}
          {state.status === 'none' && (
            <Text>This repo has no project map yet. Ask Claude to "set up the project map".</Text>
          )}
          {state.status === 'failed' && <Text>The map could not be read: {state.problem}</Text>}
          <Button key="refresh" label="Try again" onPress={() => load($)} />
        </Box>
      )
    }

    return (
      <Box flexDirection="column">
        <Text bold>{summary.title}</Text>
        <Text dimColor>
          {state.status === 'loading' ? 'Refreshing. ' : ''}Facts from GitHub at {summary.generated}.{' '}
          {summary.issues.length} open issues, {summary.merged} pull requests merged.
        </Text>
        <Box>
          <Button key="refresh" label="Refresh" onPress={() => load($)} />
          <Text> </Text>
          <Link href={FULL_MAP} label="Open the full map" />
        </Box>
        {state.status === 'failed' && <Text>Last refresh failed: {state.problem}</Text>}
        {summary.drift.length > 0 && (
          <Text>
            The map is behind the repo ({summary.drift.length}): {summary.drift.slice(0, 4).join('; ')}
            {summary.drift.length > 4 ? ' and more' : ''}. Ask Claude to "refresh the project map".
          </Text>
        )}
        {SECTIONS.map(section => {
          const rows = summary.issues.filter(issue => issue.kind === section.kind)

          if (rows.length === 0) {
            return null
          }

          return (
            <Box flexDirection="column">
              <Text> </Text>
              <Text bold>
                {section.title} ({rows.length})
              </Text>
              {rows.map(issue => (
                <Box flexDirection="column">
                  <Text>
                    #{issue.n} {issue.plain}
                  </Text>
                  <Text dimColor>
                    {'  '}
                    {issue.stage}, {touchLine(issue)}
                  </Text>
                  {section.kind === 'attention' && (issue.note || issue.hint) && (
                    <Text dimColor>
                      {'  '}
                      {issue.note} {issue.hint}
                    </Text>
                  )}
                </Box>
              ))}
            </Box>
          )
        })}
      </Box>
    )
  })
}
