import type { Edge, Node } from 'reactflow'

import type { NarratronState } from './types'

import dagre from 'dagre'

function entityColor(kind?: string): string {
  switch (kind) {
    case 'character':
      return '#60a5fa'
    case 'prop':
      return '#a78bfa'
    case 'scene':
      return '#34d399'
    default:
      return '#94a3b8'
  }
}

type FlowGroup = 'entity' | 'shot' | 'trace'

function layoutWithDagre(nodes: Node[], edges: Edge[]): Node[] {
  // Dagre computes node positions for directed graphs.
  // We keep node sizing approximations aligned with our current styles.
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({
    rankdir: 'LR', // left-to-right
    nodesep: 45,
    ranksep: 90,
  })

  const getNodeSize = (node: Node): { width: number; height: number } => {
    const group = (node.data as { group?: FlowGroup } | undefined)?.group
    switch (group) {
      case 'entity':
        return { width: 180, height: 92 }
      case 'shot':
        return { width: 220, height: 98 }
      case 'trace':
        return { width: 220, height: 110 }
      default:
        return { width: 220, height: 100 }
    }
  }

  nodes.forEach((node) => {
    const { width, height } = getNodeSize(node)
    g.setNode(node.id, { width, height })
  })
  edges.forEach((edge) => {
    g.setEdge(edge.source, edge.target)
  })

  dagre.layout(g)

  // Dagre gives center-based coordinates; ReactFlow accepts top-left-ish values.
  // We subtract half sizes so nodes render aligned with the computed layout.
  const next = nodes.map((node) => {
    const { width, height } = getNodeSize(node)
    const pos = g.node(node.id) as { x: number; y: number } | undefined
    if (!pos) {
      return node
    }
    return {
      ...node,
      position: {
        x: pos.x - width / 2,
        y: pos.y - height / 2,
      },
    }
  })

  return next
}

export function buildFlowGraph(state: NarratronState): { nodes: Node[]; edges: Edge[] } {
  const entities = state.entities ?? []
  const shots = [...(state.shots ?? [])].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
  const traces = state.traces ?? []

  const nodes: Node[] = []
  const edges: Edge[] = []

  entities.forEach((entity) => {
    nodes.push({
      id: entity.id,
      position: { x: 0, y: 0 },
      data: {
        label: entity.name || entity.id,
        meta: entity.kind || 'entity',
        group: 'entity' satisfies FlowGroup,
      },
      style: {
        background: '#111827',
        color: '#f8fafc',
        border: `1px solid ${entityColor(entity.kind)}`,
        borderRadius: 14,
        padding: 10,
        width: 180,
      },
    })
  })

  shots.forEach((shot, index) => {
    nodes.push({
      id: shot.id,
      position: { x: 0, y: 0 },
      data: {
        label: `Shot ${shot.order ?? index + 1}`,
        meta: shot.camera_language || 'camera language missing',
        group: 'shot' satisfies FlowGroup,
      },
      style: {
        background: '#1f2937',
        color: '#f8fafc',
        border: '1px solid #f59e0b',
        borderRadius: 14,
        padding: 10,
        width: 220,
      },
    })
  })

  traces.forEach((trace) => {
    nodes.push({
      id: trace.id,
      position: { x: 0, y: 0 },
      data: {
        label: trace.cause || trace.effect || trace.id,
        meta: trace.effect || 'trace_log',
        group: 'trace' satisfies FlowGroup,
      },
      style: {
        background: '#3f1d2e',
        color: '#fdf2f8',
        border: '1px solid #fb7185',
        borderRadius: 18,
        padding: 10,
        width: 220,
      },
    })

    if (trace.entity_id) {
      edges.push({
        id: `${trace.id}-entity-${trace.entity_id}`,
        source: trace.entity_id,
        target: trace.id,
        animated: false,
        label: 'state source',
      })
    }

    if (trace.shot_id) {
      edges.push({
        id: `${trace.id}-shot-${trace.shot_id}`,
        source: trace.id,
        target: trace.shot_id,
        animated: true,
        label: 'shot effect',
      })
    }
  })

  const laidOutNodes = layoutWithDagre(nodes, edges)
  return { nodes: laidOutNodes, edges }
}
