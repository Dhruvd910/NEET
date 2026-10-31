import Articles from "@/components/Articles";
import { Microscope } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { Notice } from "@/components/ui";

export default function NeetInfoPage() {
  return (
    <div className="space-y-5">
      <PageHeader icon={Microscope} eyebrow="Know your exam" title="NEET-UG information hub">The exam, eligibility, applications and results — each topic linked to its official source.</PageHeader>
      <Notice tone="warn">
        Dates, patterns and rules change every year. Items marked “Pending verification” have not yet been checked against
        this year&apos;s official Information Bulletin. The official NTA website is always the final authority.
      </Notice>
      <Articles section="neet" />
    </div>
  );
}
