# PharmPort Security

## Authentication & Secrets

### Secret Management
- All credentials stored in `.env` file (git-ignored via `.gitignore`)
- Environment variables loaded via `python-dotenv`
- No hardcoded credentials in source code

### Required Environment Variables
| Variable | Purpose |
|----------|---------|
| `DATABASE_HOST` | Azure PostgreSQL hostname |
| `DATABASE_PORT` | PostgreSQL port (default: 5432) |
| `DATABASE_USER` | Database username |
| `DATABASE_PASSWORD` | Database password |
| `DATABASE_NAME` | Primary database name |
| `V2_DATABASE_NAME` | V2 database name |
| `VECTOR_DATABASE_NAME` | Vector database name |
| `DEV_DATABASE_NAME` | Development database name |
| `AZURE_EMBEDDING_ENDPOINT` | Azure OpenAI embedding API endpoint |
| `AZURE_EMBEDDING_KEY` | Azure OpenAI API key |
| `AZURE_EMBEDDING_MODEL` | Embedding model name |
| `ANTHROPIC_API_KEY` | Claude API key (medication guide generation) |
| `DEEPL_AUTH_KEY` | DeepL translation API key |

### Validation
- `common.py` raises `ValueError` on missing connection parameters at startup
- Missing keys cause immediate failure, not silent fallback

## Network Security

### Database Connections
- **SSL required**: All connections use `sslmode=require`
- **TCP keepalive**: `idle=30s, interval=10s, count=5` prevents silent disconnects
- **Azure PostgreSQL Flexible Server**: Managed infrastructure with Azure networking

### External API Communication
- All API calls over HTTPS
- API keys sent via headers (not URL parameters)
- Rate limiting prevents abuse of external services

## Data Security

### Dual-Database Isolation
- Source data (`teoul_pharminfo`) is never modified by the pipeline
- Generated content goes to `teoul_pharminfo_v2` only
- Separate connection factories enforce this separation

### SQL Injection Considerations
- **Known debt**: `batch_insert()` and `get_pending_codes()` in `enrich_base.py` use f-string interpolation for table/column names
- **Mitigation**: All inputs are internal constants, not user-supplied
- **Recommendation**: Migrate to `psycopg2.sql` module for proper identifier quoting
- Parameterized queries (`%s` placeholders) used for all value bindings

## Access Control

### Pipeline Access
- CLI-based execution on authorized machines only
- No web API or network-exposed endpoints
- `--dev` flag routes to isolated development database

### Data Classification
| Data Type | Sensitivity | Protection |
|-----------|-------------|------------|
| Medicine names/ingredients | Public | Standard DB access |
| HIRA codes | Public reference data | Standard DB access |
| API keys | Secret | .env file, git-ignored |
| DB credentials | Secret | .env file, git-ignored |
| LLM-generated content | Internal | Stored in V2 DB only |
| Patient-facing guides | Public (after review) | Expert review gate |

## Compliance Notes

- Medical content generation includes `validation_status = 'expert_reviewed'` gate for safety-critical sections
- `llm_version` tracking enables audit of which model version generated each piece of content
- All enrichment records include `source` and `fetched_at` for provenance tracking
