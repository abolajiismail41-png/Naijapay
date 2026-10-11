import { lazy, type ReactElement, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import AdminLayout, { AdminIndex } from "./admin/AdminLayout";
import { RequireAuth } from "./components/Layout";
import { Spinner } from "./components/ui";
import Support from "./components/Support";

import Account, { SetPin } from "./pages/Account";
import { Login, Register, Reset, Verify } from "./pages/auth";
import Home from "./pages/Home";
import Landing from "./pages/Landing";
import NotFound from "./pages/NotFound";

// Admin screens are code-split so customers never download them.
const Profit = lazy(() => import("./admin/Profit"));
const Pricing = lazy(() => import("./admin/Pricing"));
const Catalogue = lazy(() => import("./admin/Catalogue"));
const AdminTransactions = lazy(() => import("./admin/AdminTransactions"));
const PromotionsAdmin = lazy(() => import("./admin/Promotions"));
const AdminOverview = lazy(() => import("./admin/Overview"));
const AdminUsers = lazy(() => import("./admin/Users"));
const AdminAudit = lazy(() => import("./admin/Audit"));
const RiskOperations = lazy(() => import("./admin/RiskOperations"));

// Customer pages
const Activity = lazy(() => import("./pages/Activity"));
const Airtime = lazy(() => import("./pages/Airtime"));
const Data = lazy(() => import("./pages/Data"));
const Electricity = lazy(() => import("./pages/Electricity"));
const ExamPins = lazy(() => import("./pages/ExamPins"));
const Fund = lazy(() => import("./pages/Fund"));
const FundResult = lazy(() => import("./pages/FundResult"));
const Pay = lazy(() => import("./pages/Pay"));
const TransactionDetail = lazy(
  () => import("./pages/TransactionDetail"),
);
const TV = lazy(() => import("./pages/TV"));
const Notifications = lazy(() => import("./pages/Notifications"));
const Rewards = lazy(() => import("./pages/Rewards"));

const wait = (element: ReactElement) => (
  <Suspense fallback={<Spinner />}>{element}</Suspense>
);

export default function App() {
  return (
    <Routes>
      {/* Public pages */}
      <Route path="/" element={<Landing />} />
      <Route path="/register" element={<Register />} />
      <Route path="/verify" element={<Verify />} />
      <Route path="/login" element={<Login />} />
      <Route path="/reset" element={<Reset />} />

      {/* Authenticated customer and admin pages */}
      <Route element={<RequireAuth />}>
        <Route path="/home" element={<Home />} />

        {/* Customer support */}
        <Route
          path="/support"
          element={
            <div className="stack">
              <h1>Customer Support</h1>
              <Support />
            </div>
          }
        />

        {/* Payments */}
        <Route path="/pay" element={wait(<Pay />)} />
        <Route path="/pay/airtime" element={wait(<Airtime />)} />
        <Route path="/pay/data" element={wait(<Data />)} />
        <Route
          path="/pay/electricity"
          element={wait(<Electricity />)}
        />
        <Route path="/pay/exam-pins" element={wait(<ExamPins />)} />
        <Route path="/pay/tv" element={wait(<TV />)} />

        {/* Wallet funding */}
        <Route path="/fund" element={wait(<Fund />)} />
        <Route path="/fund/result" element={wait(<FundResult />)} />

        {/* Activity and transactions */}
        <Route path="/activity" element={wait(<Activity />)} />
        <Route
          path="/activity/:ref"
          element={wait(<TransactionDetail />)}
        />

        {/* Notifications and rewards */}
        <Route
          path="/notifications"
          element={wait(<Notifications />)}
        />
        <Route path="/rewards" element={wait(<Rewards />)} />

        {/* Account */}
        <Route path="/account" element={<Account />} />
        <Route path="/account/pin" element={<SetPin />} />

        {/* Admin */}
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<AdminIndex />} />
          <Route
            path="overview"
            element={wait(<AdminOverview />)}
          />
          <Route path="users" element={wait(<AdminUsers />)} />
          <Route path="audit" element={wait(<AdminAudit />)} />
          <Route path="profit" element={wait(<Profit />)} />
          <Route path="pricing" element={wait(<Pricing />)} />
          <Route path="catalogue" element={wait(<Catalogue />)} />
          <Route
            path="transactions"
            element={wait(<AdminTransactions />)}
          />
          <Route
            path="promotions"
            element={wait(<PromotionsAdmin />)}
          />
          <Route path="risk" element={wait(<RiskOperations />)} />
        </Route>
      </Route>

      {/* Fallback routes */}
      <Route
        path="/index.html"
        element={<Navigate to="/" replace />}
      />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}