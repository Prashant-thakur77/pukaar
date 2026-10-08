# Rioplatense Hydrological Corpus

Labeled corpus of Litoral-region Spanish flood reports, used to evaluate
structured extraction (`transcript_es` -> SINAME-shaped enums).

- File: `corpus.jsonl` - 82 examples, one JSON object per line.
- Splits: 55 train / 12 validation / 15 test (`split` field per row).
- Regions: Santa Fe, Corrientes, Chaco, Entre Rios, Formosa, Buenos Aires
  conurbano.
- Benchmark and label schema: [`../../docs/Project/rioplatense_eval.md`](../../docs/Project/rioplatense_eval.md).

## Provenance

Authored by the project contributors for this project. The phrasings are
written to mirror how volunteers report flooding in Rioplatense/Litoral
Spanish (`paso la marca`, `tapo la calle`, `ya toca el puente`, `subiendo
rapido`). They are not transcriptions of real messages: no example is
copied from WhatsApp groups, social media, or any third-party dataset, and
the corpus contains no personal data.

## License

CC BY 4.0, same as the rest of the repository. See [`../../LICENSE`](../../LICENSE).

Attribution:

> "Rioplatense Hydrological Corpus", from "Pukaar" by the
> Pukaar contributors, licensed under CC BY 4.0.
> Source: https://
