import { createRouter, createWebHistory } from 'vue-router'
import ChatPage from '../pages/ChatPage.vue'
import HistoryPage from '../pages/HistoryPage.vue'
import OngoingPage from '../pages/OngoingPage.vue'
import SessionPage from '../pages/SessionPage.vue'

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
      name: 'session',
      component: SessionPage,
      props: true,
      meta: {
        title: 'AI Agent - Session'
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
    }
  ]
})

// 페이지 타이틀 업데이트
router.afterEach((to) => {
  document.title = to.meta.title as string || 'AI Agent'
})

export default router
