import { NavLink } from 'react-router-dom';
import './NavBar.css';

function NavBar() {
  return (
    <nav className="navbar">
      <span className="navbar-brand">Stock Council</span>
      <div className="navbar-links">
        <NavLink to="/" end className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          Dashboard
        </NavLink>
        <NavLink to="/scorecard" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          Scorecard
        </NavLink>
        <NavLink to="/chat" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          Chat
        </NavLink>
      </div>
    </nav>
  );
}

export default NavBar;
