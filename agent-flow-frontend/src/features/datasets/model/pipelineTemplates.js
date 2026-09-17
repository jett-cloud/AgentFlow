/**
 * Empty RAG pipeline seed — mirrors Dify use-pipeline-template.ts
 * (single knowledge-index / Knowledge Base node).
 * Keep free of Vue/@ aliases so Node tests can import it.
 */

export const PIPELINE_START_POSITION = { x: 80, y: 282 }

export function buildEmptyPipelineGraph() {
  return {
    nodes: [
      {
        id: 'knowledgeBase',
        type: 'knowledge-index',
        position: {
          x: PIPELINE_START_POSITION.x + 500,
          y: PIPELINE_START_POSITION.y,
        },
        data: {
          type: 'knowledge-index',
          title: '知识库',
          selected: true,
        },
      },
    ],
    edges: [],
  }
}
