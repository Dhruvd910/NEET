import Articles from "@/components/Articles";
import { Dna } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { Notice } from "@/components/ui";

export default function CareersPage() {
  return (
    <div className="space-y-5">
      <PageHeader icon={Dna} eyebrow="Beyond MBBS" title="Other healthcare & life-science pathways">
        MBBS is one of many ways to build a career in health. These pathways have their own entrance routes and rules.
      </PageHeader>
      <Notice>Not every pathway uses NEET or NEET counselling. Check each course&apos;s current admission notice before deciding.</Notice>
      <Articles section="careers" />
    </div>
  );
}
