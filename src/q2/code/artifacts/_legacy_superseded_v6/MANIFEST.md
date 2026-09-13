# 旧产物归档 manifest（q2-legacy-superseded-v6）

- 生成时间：2026-09-11T15:51:16.252646+08:00
- 生成工具：`src/q2/code/tools/archive_q2_legacy_artifacts.py`
- 归档根目录：`src/q2/code/artifacts/_legacy_superseded_v6`
- 归档方式：copy-only（复制，不移动、不删除）
- 范围内文件：71
- 已复制并校验：71 / 71
- 缺失（未找到，不报错）：0
- `legacy_generator_unavailable`：True

## 旧配置来源核查

- 顶层 run config：`src/q2/code/artifacts/q2_final_evidence_config.json` → config_id = `q2-final-evidence-v6-dynamic-closure`
- probe run config：`src/q2/code/artifacts/gate_g_production_probe/q2_final_evidence_config.json` → config_id = `q2-final-evidence-v2-production`

核查方式：优先读取文件内嵌的 `config_id` / `evidence_config_id` / `source_config_id` 字段（`embedded_field`，strong）；未命中但位于 `gate_g_production_probe/`（该目录自带 config 文件）记为 `group_directory_embedded_config`（medium）；再退一步，若文件与某条带 v6 id 的文件共享 `qhat_star` / `threshold` / `approximate_area_m2` 数值字面量，记为 `content_value_match`（medium）；其余仅按目录归属推断，记为 `directory_inference`（weak）。**没有使用 mtime 作为证据。**

## 缺失文件

（无）

## 归档前后文件计数

| 目录 | 归档前 | 归档后 |
|---|---:|---:|
| `src/q2/code`（排除 __pycache__ / archive） | 236 | 236 |
| `src/q2/code/artifacts`（排除 archive） | 110 | 110 |
| `src/q2/code/figures` | 37 | 37 |

源计数未变化：**True**；删除源文件：**False**

## 条目

| path | bytes | sha256 | legacy_config_source | basis | B1/B2 labeling |
|---|---:|---|---|---|---|
| `src/q2/code/artifacts/gate_g_production_probe/q2_angular_image.json` | 731496 | `c7bdb7d721b1509c327c27c87692d2311c30372a1f97f4c1c1e866b1056113fd` | `src/q2/code/artifacts/gate_g_production_probe/q2_angular_image.json` | embedded_field | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_baseline_comparison.json` | 731502 | `ce823858cc764c4349d018446e5640c3783f38cf0ad796fdcef304eefdb1f981` | `src/q2/code/artifacts/gate_g_production_probe/q2_baseline_comparison.json` | embedded_field | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_candidate_good_eta_01.json` | 28043 | `1e46806c1fe5f6224e4cd64d7b5c61d47967ad5089e3b11a36b6827b07268597` | `src/q2/code/artifacts/gate_g_production_probe/q2_final_evidence_config.json` | group_directory_embedded_config | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_candidate_good_eta_02.json` | 50946 | `f7428b27623513cbd8e13e4f15773e5b0f5a23597a3085e8f6968b9b048d9177` | `src/q2/code/artifacts/gate_g_production_probe/q2_final_evidence_config.json` | group_directory_embedded_config | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_candidate_good_eta_05.json` | 74244 | `80cf02c8e2f8f8b9a71d61de3f3677c629bc39cb72f84893d93fe818fbd6694b` | `src/q2/code/artifacts/gate_g_production_probe/q2_final_evidence_config.json` | group_directory_embedded_config | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_candidate_good_eta_10.json` | 89869 | `4d370e02b12cf88d63af240778164db208df1fdc0b3616bbccd3ecdf7e6add8b` | `src/q2/code/artifacts/gate_g_production_probe/q2_final_evidence_config.json` | group_directory_embedded_config | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_candidate_good_regions.json` | 263748 | `2afa77ada25f829c9d4052ef1d646eaa7da356e728c112a416ab754ecd9138e7` | `src/q2/code/artifacts/gate_g_production_probe/q2_candidate_good_regions.json` | embedded_field | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_candidate_region_eta_01.geojson` | 77807 | `f8dd0772fa418a09821ce5573dc9c926c1f33e8cf4f5d88e069b3d95b25b23f3` | `src/q2/code/artifacts/gate_g_production_probe/q2_candidate_region_eta_01.geojson` | embedded_field | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_candidate_region_eta_02.geojson` | 181923 | `26fd4e0173d207169e3559656fccf475487f99d040523c3cffc2f83e33f0bcd3` | `src/q2/code/artifacts/gate_g_production_probe/q2_candidate_region_eta_02.geojson` | embedded_field | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_candidate_region_eta_05.geojson` | 289485 | `30560679ce8d16ee6475f68dff6855ac9b3492b237fbb8f16dd6093e11d66591` | `src/q2/code/artifacts/gate_g_production_probe/q2_candidate_region_eta_05.geojson` | embedded_field | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_candidate_region_eta_10.geojson` | 362727 | `6365ca4caffabfd05f3f42776579d9d284af686379c786dfaa63c3cf7a1d2f37` | `src/q2/code/artifacts/gate_g_production_probe/q2_candidate_region_eta_10.geojson` | embedded_field | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_crec.json` | 731487 | `c974bd4d91397ef1588f4c4a31108de57d2e7e8deeb32cb907c5a57fd605492a` | `src/q2/code/artifacts/gate_g_production_probe/q2_crec.json` | embedded_field | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_evidence_table.json` | 2259 | `566739fdeb919f3c4b6e2a9f24a486f27e228e24b0c624c145b91558b53c890c` | `src/q2/code/artifacts/gate_g_production_probe/q2_evidence_table.json` | embedded_field | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_final_evidence_config.json` | 694 | `0c5d1bce4e7cb63eef464091120cba36f3188df224de4671aa80d32da6771196` | `src/q2/code/artifacts/gate_g_production_probe/q2_final_evidence_config.json` | self_config_file | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_geometry_overview.json` | 731500 | `5a1347c88fa46904f2189d765e67d745e1c70b44c981aee3d86a651af1ec3c6a` | `src/q2/code/artifacts/gate_g_production_probe/q2_geometry_overview.json` | embedded_field | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_method_provenance.json` | 488 | `64b1e8af7f1e6545fda5f407cd32fc61b56b33dc70913c097dbd68e7872de2a9` | `src/q2/code/artifacts/gate_g_production_probe/q2_final_evidence_config.json` | group_directory_embedded_config | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_optimum_and_candidate_region.json` | 731511 | `f6b30c8b171f549f19301fa202426adea14c1f3d2893c9846127a42ea9671b38` | `src/q2/code/artifacts/gate_g_production_probe/q2_optimum_and_candidate_region.json` | embedded_field | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_q_surface.json` | 731492 | `fb133c1de10538e422efa942ce516e16e719c47d2e83f8ffbcf4845b830dbd36` | `src/q2/code/artifacts/gate_g_production_probe/q2_q_surface.json` | embedded_field | True |
| `src/q2/code/artifacts/gate_g_production_probe/q2_worst_case_intersection.json` | 731506 | `bbfe1699636520ca8b625666141046a48513405f00772e81abd5db3c71e15589` | `src/q2/code/artifacts/gate_g_production_probe/q2_worst_case_intersection.json` | embedded_field | True |
| `src/q2/code/artifacts/q2_baseline_comparison.csv` | 599 | `f57c227910ad026101f69517dabe71d7e190af1c1747cffd8582e8de4c3734c3` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/artifacts/q2_candidate_region_eta_01.geojson` | 132294 | `08790679fa6771b2ae4caf2667dc78079d1ee71fb394c017e6baa514c7ea4063` | `src/q2/code/artifacts/q2_candidate_region_eta_01.geojson` | embedded_field | True |
| `src/q2/code/artifacts/q2_candidate_region_eta_02.geojson` | 256686 | `cc5848725525ed483b3165de6b3a25cc9ba6f6d92f7c5977cdb05d5a11d429d1` | `src/q2/code/artifacts/q2_candidate_region_eta_02.geojson` | embedded_field | True |
| `src/q2/code/artifacts/q2_candidate_region_eta_05.geojson` | 373052 | `1beae83c999a6a00b2e9b9e633af8776942b6417ea17554a1596748c6dea8113` | `src/q2/code/artifacts/q2_candidate_region_eta_05.geojson` | embedded_field | True |
| `src/q2/code/artifacts/q2_candidate_region_eta_10.geojson` | 446753 | `78171b092cdc193a9d5f4cf72918982e6a2da395fc36c0767a1bc171bcc98098` | `src/q2/code/artifacts/q2_candidate_region_eta_10.geojson` | embedded_field | True |
| `src/q2/code/artifacts/q2_candidate_regions.json` | 344413 | `ce128f44e4e8bdbc2e7e0f46fcbf7a969dbe888d253e77e5f23ea71b76533a20` | `src/q2/code/artifacts/q2_candidate_regions.json` | embedded_field | True |
| `src/q2/code/artifacts/q2_evidence_table.json` | 2266 | `64dc226dfe74eec0ba30afd8de1d52f15360d0b62c18d456413cdc4ce246cf72` | `src/q2/code/artifacts/q2_evidence_table.json` | embedded_field | True |
| `src/q2/code/artifacts/q2_final_evidence_config.json` | 923 | `0867f992a44cd2d3618b39a0260701efcb9f6d0876ecbed2dafc68b985d18c94` | `src/q2/code/artifacts/q2_final_evidence_config.json` | self_config_file | True |
| `src/q2/code/artifacts/q2_final_verification_report.json` | 1846 | `0fe42bc5304d574f559b4e607a1233e7e5d51997ebba4613e9542f3ae9f770c0` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/artifacts/q2_model_spec.json` | 1746 | `715445459571d412acc10fe1eb6cf72bcd06aef909f17ff018ab9603dcb3d6f5` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/artifacts/q2_regression_cases.json` | 982 | `cbbc00bbaa40ad2830198ba81343c197362e7adfa1d5f7822a456a3ea974ebf4` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/artifacts/q2_run_manifest.json` | 1494 | `c4b360870f63820c8e4220e22d0a19c101728c5a6f5ef3335ff21e3472b8aab7` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/artifacts/q2_solution_examples.json` | 921 | `be18105c04ea9654a778d3a3d2ef8bb1b4d28fb85c6cf5abd4f49d4b1cb13ca8` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/artifacts/q2_solver_config.json` | 894 | `4872e3371e26b5f31edc2a53aaaf057f41439ccb1e1c3087ae6f9ce50cf89f55` | `src/q2/code/artifacts/q2_solver_config.json` | self_config_file | True |
| `src/q2/code/artifacts/q2_visual_qa_report.json` | 610 | `abce1dd23fb11c62bd609ebfcd358fd17714480b64dc69f213cd1fc080dff219` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_angular_image.json` | 900461 | `408fc88dd8774424cad551d5af0e7dafbfb3c2f5084d1908345bcf2fbf554f61` | `src/q2/code/figures/q2_angular_image.json` | embedded_field | True |
| `src/q2/code/figures/q2_angular_image.pdf` | 32865 | `fa80eb2e35ce05eb2aed494dd3425037227d11fbe7f12e05501ea1537eddf01a` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_angular_image.png` | 63921 | `1edeccf89f8ea57a79e791ac86578bd9c391fc52c84633ee5fdfbf68d8c8f0f1` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_angular_image.svg` | 15146 | `a4c33e77a91f4c38ae723ec1289e5a6bc9438c88f63ba79eb447d1b7befc8330` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_baseline_comparison.json` | 900467 | `db6a2c6e178f90a1a137011eb9a0c7ca29bfa59be4f6174ea1daf2ec60f7d42c` | `src/q2/code/figures/q2_baseline_comparison.json` | embedded_field | True |
| `src/q2/code/figures/q2_baseline_comparison.pdf` | 23652 | `320caa5eae01bb3c26c62981c468c90a49e01b02dbb7512da55c89a882b33020` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_baseline_comparison.png` | 51558 | `7ab8abc9ed1be790ed2dd13aa306bb4233f19c7be861616277c228afd01b375c` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_baseline_comparison.svg` | 10298 | `7d263a25198bafa91d3ed272f459c9039e9afbd698f2b67e82d92c46fc5675fd` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_candidate_good_eta_01.json` | 46559 | `2b366b14f38caa1156aab95e2ae751f705a1c49296357f49ffea5547eccae5b4` | `src/q2/code/artifacts/q2_final_evidence_config.json` | content_value_match | True |
| `src/q2/code/figures/q2_candidate_good_eta_02.json` | 72758 | `4de80e219807b65a844dfd20258edbcc0f897ef5f6cb65c9fb7d3efb6de626b9` | `src/q2/code/artifacts/q2_final_evidence_config.json` | content_value_match | True |
| `src/q2/code/figures/q2_candidate_good_eta_05.json` | 98992 | `60e9d01d1d2e090beb6fa82d184f76583fcad785a8fa6577ee643f86cbd40495` | `src/q2/code/artifacts/q2_final_evidence_config.json` | content_value_match | True |
| `src/q2/code/figures/q2_candidate_good_eta_10.json` | 114876 | `914650a69a72b80eb480261f0e8d7b7a44059967d492fbd4afed1a5a37f5c3ed` | `src/q2/code/artifacts/q2_final_evidence_config.json` | content_value_match | True |
| `src/q2/code/figures/q2_candidate_good_regions.json` | 344413 | `ce128f44e4e8bdbc2e7e0f46fcbf7a969dbe888d253e77e5f23ea71b76533a20` | `src/q2/code/figures/q2_candidate_good_regions.json` | embedded_field | True |
| `src/q2/code/figures/q2_crec.json` | 900452 | `7b766a951a3af5da997a50079064fed70349281440b85046423101d70e98d535` | `src/q2/code/figures/q2_crec.json` | embedded_field | True |
| `src/q2/code/figures/q2_crec.pdf` | 34146 | `de6d2543eb54fce4e699f773193b0dffde46f5c7a3a8b9a64a279872c614a9d0` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_crec.png` | 114062 | `7cffd4ae9f3d9088ffbf49be74e67c80f56e17d5a2ae092fb5cb2734b6f2efd7` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_crec.svg` | 224606 | `bd2c4b5f95370630418a4efa05b59960159959cee1839b54561063beeebcb5f7` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_evidence_table.json` | 2266 | `64dc226dfe74eec0ba30afd8de1d52f15360d0b62c18d456413cdc4ce246cf72` | `src/q2/code/figures/q2_evidence_table.json` | embedded_field | True |
| `src/q2/code/figures/q2_final_evidence_config.json` | 923 | `0867f992a44cd2d3618b39a0260701efcb9f6d0876ecbed2dafc68b985d18c94` | `src/q2/code/figures/q2_final_evidence_config.json` | self_config_file | True |
| `src/q2/code/figures/q2_geometry_overview.json` | 900465 | `8ac2c457a101c2b5794f791f8a59b79414ad499da5722111ac5e3808af7fcd7a` | `src/q2/code/figures/q2_geometry_overview.json` | embedded_field | True |
| `src/q2/code/figures/q2_geometry_overview.pdf` | 28940 | `88c328ea84fb3e60731d2e0bedd8dec402be70c0463bf201d31907d688144c0e` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_geometry_overview.png` | 105780 | `b040a1a45b31d615c31e1a90e46c080e96b8d00419bed852da4561504bc2e724` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_geometry_overview.svg` | 32902 | `068237aa8eadf704f99afc8e883ad8beabeabc52a2ff2ba8a893e86f6c7ca49e` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_hero_closure.json` | 4329 | `df8a44745eda82b05a28c6da2ecf5290797bba0f502b5f8c884afd40b1297828` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_method_provenance.json` | 488 | `64b1e8af7f1e6545fda5f407cd32fc61b56b33dc70913c097dbd68e7872de2a9` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_optimum_and_candidate_region.json` | 900476 | `e97117161c88cb604ba61f2dc9e6ae9a53b59bae39e338c62d6fa4af5623556a` | `src/q2/code/figures/q2_optimum_and_candidate_region.json` | embedded_field | True |
| `src/q2/code/figures/q2_optimum_and_candidate_region.pdf` | 34836 | `f8feeeec150bd83a0a160022ee8d2522697ef5b972baa3f1bd9c2fc6a78ec981` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_optimum_and_candidate_region.png` | 66191 | `7d3816564dc063f432d3655fa5f1408e917c1dd5c6ab22b3cae70268484a76b4` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_optimum_and_candidate_region.svg` | 171495 | `4d403b06e2f104b0de8373afb8a4c6c7cfc2e8f34c5272ee3a864fa652852071` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_q_surface.json` | 900457 | `d06f11e673fee3c08245e6a269ad0dcdae2038c1837282a2d7814e8faf04cb97` | `src/q2/code/figures/q2_q_surface.json` | embedded_field | True |
| `src/q2/code/figures/q2_q_surface.pdf` | 29597 | `44e53d86f6386a62cdc87f40c38c5198c1feabee01983f8812645c4c40afb492` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_q_surface.png` | 91775 | `5e7a270aa0e9fd7239e9e24abe433b31b0e0cf7957234aa69a6bb28a6334004b` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_q_surface.svg` | 175380 | `3b6202b73317b42eec80e225c18f40e6bb696687dd57e70d4bf95cdaf3032338` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_worst_case_intersection.json` | 900471 | `5a623cce64d94b8f1c8e4dce9fe1cad2c5b759d8898ec3de2e7dea55141303d9` | `src/q2/code/figures/q2_worst_case_intersection.json` | embedded_field | True |
| `src/q2/code/figures/q2_worst_case_intersection.pdf` | 26290 | `a04d257a63990139a5b9f1efc0499c5bf3a2c1ce50cb0f52e5e8d292e437e880` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_worst_case_intersection.png` | 64860 | `7e8cb185f06310f7477bd57feb169d1dbcb14c264964c64fdb47a7a95c98c888` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
| `src/q2/code/figures/q2_worst_case_intersection.svg` | 18700 | `1c6b56b8b3e6e02e4bd277b41fc9c1a5e060cd3081cb350a52b939035ff3f8f6` | `src/q2/code/artifacts/q2_final_evidence_config.json` | directory_inference | True |
