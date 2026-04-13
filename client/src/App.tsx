import AppDesktop from "./AppDesktop";
import AppMobile from "./AppMobile";

const isMobile = /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent);

export default function App() {
  return isMobile ? <AppMobile /> : <AppDesktop />;
}
