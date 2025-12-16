import { createBrowserRouter } from 'react-router-dom'
import ChatPage from './pages/ChatPage'
import QnAPage from './pages/QnAPage'
import RoomsPage from './pages/RoomsPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <ChatPage />,
  },
  {
    path: '/info/qna',
    element: <QnAPage />,
  },
  {
    path: '/info/rooms',
    element: <RoomsPage />,
  },
])
