import { createRouter, createWebHistory } from 'vue-router'
import ChatPage from '../pages/ChatPage.vue'
import HistoryPage from '../pages/HistoryPage.vue'
import OngoingPage from '../pages/OngoingPage.vue'
import TaskRewritePage from '../pages/TaskRewritePage.vue'
import TaskRewriteHistoryPage from '../pages/TaskRewriteHistoryPage.vue'
import TaskRewriteDetailPage from '../pages/TaskRewriteDetailPage.vue'
import GeminiLogsPage from '../pages/GeminiLogsPage.vue'
import GeminiLogDetailPage from '../pages/GeminiLogDetailPage.vue'
import ValuatorSessionsPage from '../pages/ValuatorSessionsPage.vue'
import ValuatorSessionPage from '../pages/ValuatorSessionPage.vue'
import ValuatorTaskDetailPage from '../pages/ValuatorTaskDetailPage.vue'
import ValuatorFinalPage from '../pages/ValuatorFinalPage.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'chat',
      component: ChatPage,
      meta: {
        title: 'AI Agent - Chat'
      }
    },
    {
      path: '/ongoing',
      name: 'ongoing',
      component: OngoingPage,
      meta: {
        title: 'AI Agent - Active Sessions'
      }
    },
    {
      path: '/session/:sessionId',
      redirect: to => `/sessions/${String(to.params.sessionId || '')}`,
      meta: {
        title: 'Valuator - Session Detail'
      }
    },
    {
      path: '/history',
      name: 'history',
      component: HistoryPage,
      meta: {
        title: 'AI Agent - History'
      }
    },
    {
      path: '/history/:sessionId',
      name: 'history-detail',
      component: HistoryPage,
      props: true,
      meta: {
        title: 'AI Agent - Session Detail'
      }
    },
    {
      path: '/sessions',
      name: 'valuator-sessions',
      component: ValuatorSessionsPage,
      meta: {
        title: 'Valuator - Sessions'
      }
    },
    {
      path: '/sessions/:sessionId',
      name: 'valuator-session-detail',
      component: ValuatorSessionPage,
      props: true,
      meta: {
        title: 'Valuator - Session Detail'
      }
    },
    {
      path: '/sessions/:sessionId/tasks/:taskId',
      name: 'valuator-task-detail',
      component: ValuatorTaskDetailPage,
      props: true,
      meta: {
        title: 'Valuator - Task Detail'
      }
    },
    {
      path: '/sessions/:sessionId/final',
      name: 'valuator-final',
      component: ValuatorFinalPage,
      props: true,
      meta: {
        title: 'Valuator - Final'
      }
    },
    {
      path: '/rewrite',
      name: 'task-rewrite',
      component: TaskRewritePage,
      meta: {
        title: 'AI Agent - Task Rewrite'
      }
    },
    {
      path: '/rewrite/history',
      name: 'task-rewrite-history',
      component: TaskRewriteHistoryPage,
      meta: {
        title: 'AI Agent - Task Rewrite History'
      }
    },
    {
      path: '/rewrite/history/:id',
      name: 'task-rewrite-detail',
      component: TaskRewriteDetailPage,
      props: true,
      meta: {
        title: 'AI Agent - Task Rewrite Detail'
      }
    },
    {
      path: '/dev/gemini-logs',
      name: 'gemini-logs',
      component: GeminiLogsPage,
      meta: {
        title: 'Developer - Gemini Logs'
      }
    },
    {
      path: '/dev/gemini-logs/:filename',
      name: 'gemini-log-detail',
      component: GeminiLogDetailPage,
      props: true,
      meta: {
        title: 'Developer - Gemini Log Detail'
      }
    }
  ]
})

// 페이지 타이틀 업데이트
router.afterEach((to) => {
  document.title = to.meta.title as string || 'AI Agent'
})

export default router
