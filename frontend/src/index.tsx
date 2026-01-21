/* @refresh reload */
import { render } from 'solid-js/web';
import { Router, Route } from '@solidjs/router';
import './index.css';
import App from './App';
import SessionRedirect from './components/SessionRedirect';

const root = document.getElementById('root');

render(
  () => (
    <Router>
      <Route path="/" component={SessionRedirect} />
      <Route path="/:sessionId/*" component={App} />
    </Router>
  ),
  root!
);
