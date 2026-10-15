import { FileJson, LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

type Props = {
  name: string;
  fileName: string;
  summary: string;
  disabled: boolean;
  canEdit: boolean;
  importing: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

export function CatalogueImportReview({ name, fileName, summary, disabled, canEdit, importing, onConfirm, onCancel }: Props) {
  return <section className="catalogue-settings-import" aria-label="Import preview">
    <div className="catalogue-settings-import-heading">
      <FileJson size={20} aria-hidden="true" />
      <div><span className="catalogue-settings-eyebrow">Ready to import</span><h4>{name}</h4><span className="catalogue-settings-file-name">{fileName}</span></div>
    </div>
    <p className="catalogue-settings-import-counts">{summary}</p>
    <p>This replaces your current catalogue. Live listening starts separately.</p>
    <div className="catalogue-settings-import-actions">
      <Button type="button" disabled={!canEdit || disabled} aria-busy={importing} onClick={onConfirm}>
        {importing && <LoaderCircle className="animate-spin" aria-hidden="true" />}Replace saved catalogue
      </Button>
      <Button type="button" variant="ghost" disabled={disabled} onClick={onCancel}>Cancel import</Button>
    </div>
  </section>;
}
