import { BoltIcon, CapIcon, PhoneIcon, SignalIcon, TvIcon, SmsIcon } from "../components/icons";

export const SERVICES = [
  { key: "airtime", title: "Airtime", sub: "MTN, Airtel, Glo, 9mobile", to: "/pay/airtime", Icon: PhoneIcon },
  { key: "data", title: "Data", sub: "Bundles for every network", to: "/pay/data", Icon: SignalIcon },
  { key: "number", title: "Number verifications", sub: "sms verification numbers", to: "/pay/virtual-numbers", Icon: SmsIcon },
  { key: "electricity", title: "Electricity", sub: "Prepaid and postpaid meters", to: "/pay/electricity", Icon: BoltIcon },
  { key: "exam", title: "Exam PINs", sub: "WAEC and NECO result checkers", to: "/pay/exam-pins", Icon: CapIcon },
  { key: "tv", title: "TV subscriptions", sub: "DStv, GOtv and StarTimes packages", to: "/pay/tv", Icon: TvIcon },
] as const;
