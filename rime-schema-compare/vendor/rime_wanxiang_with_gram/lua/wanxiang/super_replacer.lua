--[[
super_replacer.lua 一个rime OpenCC替代品，更灵活地配置能力
https://github.com/amzxyz/rime_wanxiang
by amzxyz
路径检测：UserDir > SharedDir
支持 option: true (常驻启用)
super_replacer:
    db_name: lua/replacer
    delimiter: "|"
    comment_format: "〔%s〕"
    chain: true  #true表示流水线作业，上一个option产出交给下一个处理，典型的s2t>t2hk=s2hk，false就是并行，直接用text转换
    rules:
      # 场景1：输入 '哈哈' -> 变成 '1.哈哈 2.😄'
      - option: emoji          # 开关名称与上面开关名称保持一致
        mode: append            # 新增候选append 替换原候选replace 替换注释comment
        comment_mode: none      # 注释模式: "append"(原候选注释继承), "text"(原候选文本放在注释), "none"(空，默认)
        tags: [abc]            # 生效的tag
        prefix: "_em_"          # 前缀用于区分同一个数据库的不同用途数据
        files:
          - lua/data/emoji.txt
      # 场景2：输入 'hello' -> 显示 'hello 〔你好 | 哈喽〕'
      - option: chinese_english
        mode: append        # <--- 添加注释模式
        comment_mode: none
        tags: [abc]
        prefix: "_en_"
        files:
          - lua/data/english_chinese.txt
          - lua/data/chinese_english.txt
      # 场景3：用于常驻的直接替换 option: true
      - option: true
        mode: append        # <--- 新增候选模式
        comment_mode: none
        tags: [abc]
        prefix: "_ot_"
        files:
          - lua/data/others.txt
      # 场景4：用于简繁转换的直接替换
      - option: [ s2t, s2hk, s2tw ]  #后面依赖这条流水线有一个开关为true这条流水线就能工作
        mode: replace        # <--- 替换原候选模式
        comment_mode: append
        sentence: true        # <--- 句子级别替换
        tags: [abc]
        prefix: "_s2t_"
        files:
          - lua/data/STCharacters.txt
          - lua/data/STPhrases.txt
      - option: s2hk
        mode: replace        # <--- 替换原候选模式
        comment_mode: append
        sentence: true        # <--- 句子级别替换
        tags: [abc]
        prefix: "_s2hk_"
        files:
          - lua/data/HKVariants.txt
          - lua/data/HKVariantsRevPhrases.txt
      - option: s2tw
        mode: replace        # <--- 替换原候选模式
        comment_mode: append
        sentence: true        # <--- 句子级别替换
        tags: [abc]
        prefix: "_s2tw_"
        files:
          - lua/data/TWVariants.txt
          - lua/data/TWVariantsRevPhrases.txt
      - option: [ abbrev_lazy, abbrev_always ]
        mode: abbrev          # <--- 新增的简码模式
        tags: [abc]
        prefix: "_abbr_"
        files:
          - lua/data/abbrev.txt # 格式：zm\t怎么|在吗
        #t9_optimization: true  #t9优化,从txt里编码转换为实际打字需要的编码，例如九键维护用字母加载数据库变数字,源编码携带上用于preedit
]]
local M = {}

-- 性能优化：本地化常用库函数
local insert = table.insert
local concat = table.concat
local s_match = string.match
local s_gmatch = string.gmatch
local s_format = string.format
local s_byte = string.byte
local s_sub = string.sub
local s_gsub = string.gsub
local s_upper = string.upper
local open = io.open
local type = type
local tonumber = tonumber
local fmm_cache = {}
local replacer_instance = nil

-- 基础依赖
local function safe_require(name)
    local status, lib = pcall(require, name)
    if status then return lib end
    return nil
end

local userdb = safe_require("wanxiang/userdb")
local wanxiang = safe_require("wanxiang/wanxiang")

-- UTF-8 辅助
local function get_utf8_offsets(text)
    local offsets = {}
    local len = #text
    local i = 1
    while i <= len do
        insert(offsets, i)
        local b = s_byte(text, i)
        if b < 128 then i = i + 1
        elseif b < 224 then i = i + 2
        elseif b < 240 then i = i + 3
        else i = i + 4 end
    end
    insert(offsets, len + 1)
    return offsets
end

-- 光速文件特征采样
local function generate_files_signature(tasks)
    local sig_parts = {}
    for _, task in ipairs(tasks) do
        local f = open(task.path, "rb")
        if f then
            local size = f:seek("end")
            local head = ""
            local mid = ""
            local tail = ""
            
            if size > 0 then
                f:seek("set", 0)
                head = f:read(64) or ""
                local tail_pos = size - 64
                if tail_pos < 0 then tail_pos = 0 end
                f:seek("set", tail_pos)
                tail = f:read(64) or ""
                local mid_pos = math.floor(size / 2)
                f:seek("set", mid_pos)
                mid = f:read(64) or ""
            end
            f:close()
            insert(sig_parts, task.prefix .. size .. head .. mid .. tail)
        end
    end
    return concat(sig_parts, "||")
end

-- 重建数据库 (支持多行合并和 T9 拼接)
local function rebuild(tasks, db, delimiter)
    if db.empty then db:empty() end
    for _, task in ipairs(tasks) do
        local txt_path = task.path
        local prefix = task.prefix
        local conversion = task.conversion
        local p_delim = task.preedit_delim 

        local f = open(txt_path, "r")
        if f then
            for line in f:lines() do
                if line ~= "" and not s_match(line, "^%s*#") then
                    local k, v = s_match(line, "^([^\t]+)\t+(.+)")
                    if k and v then
                        local orig_k = k

                        if conversion then
                            k = s_gsub(k, ".", conversion)
                        end
                        
                        v = s_match(v, "^%s*(.-)%s*$")

                        if p_delim and p_delim ~= "" then
                            if not string.find(v, p_delim, 1, true) then
                                v = v .. p_delim .. orig_k
                            end
                        end

                        local db_key = prefix .. k
                        local existing_v = db:fetch(db_key)

                        if existing_v and existing_v ~= "" then
                            v = existing_v .. delimiter .. v
                        end

                        db:update(db_key, v)
                    end
                end
            end
            f:close()
        end
    end
    return true
end

-- 连接或重连数据库
local function connect_db(db_name, current_version, delimiter, tasks, config_sig)
    if replacer_instance then
        local status, _ = pcall(function() return replacer_instance:fetch("___test___") end)
        if status then return replacer_instance end
        replacer_instance = nil
    end

    if not userdb then return nil end
    local db = userdb.LevelDb(db_name)
    if not db then return nil end

    local current_signature = generate_files_signature(tasks) .. "||" .. (config_sig or "")
    
    local needs_rebuild = false
    if db:open_read_only() then
        local db_ver = db:meta_fetch("_wanxiang_ver") or ""
        local db_delim = db:meta_fetch("_delim")
        local db_sig = db:meta_fetch("_files_sig") or ""
        
        if db_ver ~= current_version or db_delim ~= delimiter or db_sig ~= current_signature then
            needs_rebuild = true
        end
        db:close()
    else
        needs_rebuild = true
    end

    if needs_rebuild then
        if db:open() then
            if db.clear then db:clear() elseif db.empty then db:empty() end
            
            rebuild(tasks, db, delimiter)
            fmm_cache = {} 
            db:meta_update("_wanxiang_ver", current_version)
            db:meta_update("_delim", delimiter)
            db:meta_update("_files_sig", current_signature) 
            
            if log and log.info then
                log.info("super_replacer: 数据已重载，最新特征已记录")
            end
            db:close()
        end
    end

    if db:open_read_only() then
        replacer_instance = db
        return db
    end
    
    return nil
end

-- FMM 分词转换算法
local function segment_convert(text, db, prefix, split_pat)
    local offsets = get_utf8_offsets(text)
    local char_count = #offsets - 1
    local result_parts = {}
    local i = 1
    local MAX_LOOKAHEAD = 6

    while i <= char_count do
        local start_byte = offsets[i]
        local matched = false
        
        local max_j = i + MAX_LOOKAHEAD
        if max_j > char_count + 1 then max_j = char_count + 1 end

        for j = max_j, i + 2, -1 do
            local end_byte = offsets[j] - 1
            local sub_text = s_sub(text, start_byte, end_byte)
            local cache_key = prefix .. sub_text
            
            local val = fmm_cache[cache_key]
            if val == nil then
                local db_res = db:fetch(cache_key)
                fmm_cache[cache_key] = db_res or false
                val = fmm_cache[cache_key]
            end
          
            if val then
                local first_val = s_match(val, split_pat)
                insert(result_parts, first_val or sub_text)
                i = j - 1
                matched = true
                break
            end
        end
      
        if not matched then
            local single_char = s_sub(text, start_byte, offsets[i+1] - 1)
            local cache_key = prefix .. single_char
            
            local val = fmm_cache[cache_key]
            if val == nil then
                local db_res = db:fetch(cache_key)
                fmm_cache[cache_key] = db_res or false
                val = fmm_cache[cache_key]
            end
            
            if val then
                local first_val = s_match(val, split_pat)
                insert(result_parts, first_val or single_char)
            else
                insert(result_parts, single_char)
            end
        end
        
        i = i + 1
    end
    return concat(result_parts)
end

-- 模块接口
function M.init(env)
    local ns = env.name_space
    ns = s_gsub(ns, "^%*", "")
    ns = string.match(ns, "([^%.]+)$") or ns
    local config = env.engine.schema.config
  
    local user_dir = rime_api.get_user_data_dir()
    local shared_dir = rime_api.get_shared_data_dir()

    local db_name = config:get_string(ns .. "/db_name") or "lua/replacer"
    local delim = config:get_string(ns .. "/delimiter") or "|"
    env.delimiter = delim
    env.comment_format = config:get_string(ns .. "/comment_format") or "〔%s〕"
    local current_version = "v0.0.1"
    if wanxiang and wanxiang.version then
        current_version = wanxiang.version
    end
    env.input_type = "unknown"
    if wanxiang and wanxiang.get_input_method_type then
        env.input_type = wanxiang.get_input_method_type(env)
    end
    env.chain = config:get_bool(ns .. "/chain")
    if env.chain == nil then env.chain = false end

    if delim == " " then env.split_pattern = "%S+"
    else local esc = s_gsub(delim, "[%-%.%+%[%]%(%)%$%^%%%?%*]", "%%%1"); env.split_pattern = "([^" .. esc .. "]+)" end

    env.rules = {}
    local tasks = {} 

    local function resolve_path(relative)
        if not relative then return nil end
        local user_path = user_dir .. "/" .. relative
        local f = open(user_path, "r")
        if f then f:close(); return user_path end
        local shared_path = shared_dir .. "/" .. relative
        f = open(shared_path, "r")
        if f then f:close(); return shared_path end
        return user_path
    end

    local rules_path = ns .. "/rules"
    local rule_list = config:get_list(rules_path)
  
    if rule_list then
        for i = 0, rule_list.size - 1 do
            local entry_path = rules_path .. "/@" .. i
          
            local triggers = {}
            local opts_keys = {"option", "options"}
            for _, key in ipairs(opts_keys) do
                local key_path = entry_path .. "/" .. key
                local list = config:get_list(key_path)
                if list then
                    for k = 0, list.size - 1 do
                        local val = config:get_string(key_path .. "/@" .. k)
                        if val then insert(triggers, val) end
                    end
                else
                    if config:get_bool(key_path) == true then
                        insert(triggers, true)
                    else
                        local val = config:get_string(key_path)
                        if val and val ~= "true" then insert(triggers, val) end
                    end
                end
            end

            local target_tags = nil
            local tag_keys = {"tag", "tags"}
            for _, key in ipairs(tag_keys) do
                local key_path = entry_path .. "/" .. key
                local list = config:get_list(key_path)
                if list then
                    if not target_tags then target_tags = {} end
                    for k = 0, list.size - 1 do
                        local val = config:get_string(key_path .. "/@" .. k)
                        if val then target_tags[val] = true end
                    end
                else
                    local val = config:get_string(key_path)
                    if val then
                        if not target_tags then target_tags = {} end
                        target_tags[val] = true
                    end
                end
            end

            if #triggers > 0 then
                local prefix = config:get_string(entry_path .. "/prefix") or ""
                local mode = config:get_string(entry_path .. "/mode") or "append"
                
                local t9_opt = config:get_bool(entry_path .. "/t9_optimization")
                local conversion_map = nil
                local preedit_delim = nil
                if t9_opt then
                    conversion_map = {}
                    local from_str = "abcdefghijklmnopqrstuvwxyz"
                    local to_str   = "22233344455566677778889999"
                    for char_idx = 1, #from_str do
                        conversion_map[s_sub(from_str, char_idx, char_idx)] = s_sub(to_str, char_idx, char_idx)
                    end
                    preedit_delim = "=="
                end

                local comment_mode = config:get_string(entry_path .. "/comment_mode")
                if not comment_mode then comment_mode = "comment" end
                local fmm = config:get_bool(entry_path .. "/sentence")
                if fmm == nil then fmm = false end
                
                -- 解析 cand_type
                local custom_cand_type = config:get_string(entry_path .. "/cand_type")

                local always_qty = 1
                local always_idx = 1
                if mode == "abbrev" then
                    local rule_str = config:get_string(entry_path .. "/abbrev_rule") or "1,1"
                    local qty_str, idx_str = s_match(rule_str, "^(%d+)%s*,%s*(%d+)$")
                    always_qty = tonumber(qty_str) or 1
                    always_idx = tonumber(idx_str) or 1
                end

                insert(env.rules, {
                    triggers = triggers,
                    tags = target_tags,
                    prefix = prefix,
                    mode  = mode,
                    always_qty = always_qty,
                    always_idx = always_idx,
                    comment_mode = comment_mode,
                    fmm = fmm,
                    preedit_delim = preedit_delim,
                    t9_opt = t9_opt,
                    cand_type = custom_cand_type -- 存入配置表
                })

                local keys_to_check = {"files", "file"}
                for _, key in ipairs(keys_to_check) do
                    local d_path = entry_path .. "/" .. key
                    local list = config:get_list(d_path)
                    if list then
                        for j = 0, list.size - 1 do
                            local p = resolve_path(config:get_string(d_path .. "/@" .. j))
                            if p then insert(tasks, { path = p, prefix = prefix, conversion = conversion_map, preedit_delim = preedit_delim }) end
                        end
                    else
                        local p = resolve_path(config:get_string(d_path))
                        if p then insert(tasks, { path = p, prefix = prefix, conversion = conversion_map, preedit_delim = preedit_delim }) end
                    end
                end
            end
        end
    end
    
    local config_sig_parts = {}
    for _, t in ipairs(env.rules) do
        insert(config_sig_parts, tostring(t.t9_opt or false) .. (t.cand_type or ""))
    end
    local config_sig = concat(config_sig_parts, "|")

    env.db = connect_db(db_name, current_version, env.delimiter, tasks, config_sig)
end

function M.fini(env)
    env.db = nil
end
local shared_pending = {}
local shared_comments = {}
local function clear_table(t)
    for i = 1, #t do
        t[i] = nil
    end
end

--解析连接符工具函数
local function parse_item(p, delim)
    if delim and delim ~= "" then
        local pos = string.find(p, delim, 1, true)
        if pos then
            return string.sub(p, 1, pos - 1), string.sub(p, pos + #delim)
        end
    end
    return p, nil
end

-- [Core Function] 核心逻辑
function M.func(input, env)
    local ctx = env.engine.context
    local input_code = ctx.input
    local db = env.db
    local rules = env.rules
    local split_pat = env.split_pattern
    local comment_fmt = env.comment_format
    local is_chain = env.chain

    if not ctx:is_composing() or ctx.input == "" then
        fmm_cache = {}
        collectgarbage("step", 200)
        for cand in input:iter() do yield(cand) end
        return
    end

    if not env.rules or #env.rules == 0 or not env.db then
        for cand in input:iter() do yield(cand) end
        return
    end

    local seg = ctx.composition:back()
    local current_seg_tags = seg and seg.tags or {}
    if seg then input_code = string.sub(ctx.input, seg.start + 1, seg._end) end
    
    local function process_rules(cand)
        local results = {}
        local current_text = cand.text
        local show_main = true
        local current_main_comment = cand.comment
        local matched_cand_type = nil -- 记录命中的自定义类型
      
        clear_table(shared_pending)
        clear_table(shared_comments)
      
        for _, t in ipairs(rules) do
            if t.mode ~= "abbrev" then
                local is_active = false
                for _, trigger in ipairs(t.triggers) do
                    if trigger == true then is_active = true; break
                    elseif type(trigger) == "string" and ctx:get_option(trigger) then is_active = true; break end
                end
              
                local is_tag_match = true
                if t.tags then
                    is_tag_match = false
                    for req_tag, _ in pairs(t.tags) do
                        if current_seg_tags[req_tag] then is_tag_match = true; break end
                    end
                end
              
                if is_active and is_tag_match then
                    local query_text = is_chain and current_text or cand.text
                    local key = t.prefix .. query_text
                    local val = db:fetch(key)
                    if not val and string.match(query_text, "[A-Z]") then
                        local lower_key = t.prefix .. string.lower(query_text)
                        val = db:fetch(lower_key)
                    end
                    if not val and t.fmm then
                        local seg_result = segment_convert(query_text, db, t.prefix, split_pat)
                        if seg_result ~= query_text then val = seg_result end
                    end
                  
                    if val then
                        matched_cand_type = t.cand_type or matched_cand_type -- 赋予候选词特权身份

                        local mode = t.mode
                        local rule_comment = ""
                        if t.comment_mode == "text" then rule_comment = cand.text
                        elseif t.comment_mode == "comment" then rule_comment = cand.comment end
                        if mode ~= "comment" and rule_comment ~= "" then
                            rule_comment = s_format(comment_fmt, rule_comment)
                        end
                        if mode == "comment" then
                            local parts = {}
                            for p in s_gmatch(val, split_pat) do 
                                -- 如果词库提示的简码，刚好等于用户当前已经敲下的编码，则不显示提示
                                if p ~= input_code then
                                    insert(parts, p) 
                                end
                            end
                            -- 只有当 parts 里有剩余有效提示时，才追加到注释数组里
                            if #parts > 0 then
                                insert(shared_comments, concat(parts, " "))
                            end
                        elseif mode == "replace" then
                            if is_chain then
                                local first = true
                                for p in s_gmatch(val, split_pat) do
                                    if first then
                                        current_text = p
                                        if t.comment_mode == "none" then current_main_comment = ""
                                        elseif t.comment_mode == "text" then current_main_comment = cand.text end
                                        first = false
                                    else
                                        insert(shared_pending, { text=p, comment=rule_comment })
                                    end
                                end
                            else
                                show_main = false
                                for p in s_gmatch(val, split_pat) do
                                    insert(shared_pending, { text=p, comment=rule_comment })
                                end
                            end
                        elseif mode == "append" then
                            for p in s_gmatch(val, split_pat) do
                                insert(shared_pending, { text=p, comment=rule_comment })
                            end
                        end
                    end
                end
            end
        end

        if #shared_comments > 0 then
            local comment_str = concat(shared_comments, " ")
            local fmt = s_format(comment_fmt, comment_str)
            current_main_comment = fmt 
        end

        if show_main then
            if is_chain and current_text ~= cand.text then
                local final_type = matched_cand_type or cand.type or "kv"
                local nc = Candidate(final_type, cand.start, cand._end, current_text, current_main_comment)
                nc.preedit = cand.preedit
                nc.quality = cand.quality
                insert(results, nc)
            else
                cand.comment = current_main_comment
                insert(results, cand)
            end
        end

        for _, item in ipairs(shared_pending) do
            if not (show_main and item.text == current_text) then
                local final_type = matched_cand_type or "derived"
                local nc = Candidate(final_type, cand.start, cand._end, item.text, item.comment)
                nc.preedit = cand.preedit
                nc.quality = cand.quality
                insert(results, nc)
            end
        end
        return results
    end

    -- 流式拦截器 + 候车室 架构
    local yield_count = 0
    local quality_dropped = false
    local has_exact_phrase = false
    local seen_texts = {}
    local global_yielded = {}
    local always_cands = {}
    local lazy_cands = {}
    local top_buffer = {}

    -- 第一步：提前提取简码候选，分配阵营
    for _, t in ipairs(rules) do
        if t.mode == "abbrev" and env.input_type ~= "pinyin" then
            local is_active = false
            for _, trigger in ipairs(t.triggers) do
                if trigger == true then is_active = true; break
                elseif type(trigger) == "string" and ctx:get_option(trigger) then is_active = true; break end
            end

            local is_tag_match = true
            if t.tags then
                is_tag_match = false
                for req_tag, _ in pairs(t.tags) do
                    if current_seg_tags[req_tag] then is_tag_match = true; break end
                end
            end

            if is_active and is_tag_match and input_code ~= "" then -- 加上输入非空保护
                local key = t.prefix .. input_code
                local val = db:fetch(key) or (not s_match(input_code, "[A-Z]") and db:fetch(t.prefix .. s_upper(input_code)))
                
                if val then
                    local count = 0
                    for p in s_gmatch(val, split_pat) do
                        local item_text, item_preedit = parse_item(p, t.preedit_delim) -- T9预编辑切割

                        if not seen_texts[item_text] then
                            seen_texts[item_text] = true
                            
                            -- 简码也支持强制注入 type
                            local final_type = t.cand_type or "abbrev"
                            local abbrev_cand = Candidate(final_type, seg and seg.start or 0, seg and seg._end or #input_code, item_text, "")
                            
                            -- 附加预编辑码
                            if item_preedit and item_preedit ~= "" then
                                abbrev_cand.preedit = item_preedit
                            end

                            count = count + 1
                            
                            if count <= t.always_qty then
                                abbrev_cand.quality = 999
                                insert(always_cands, { cand = abbrev_cand, index = t.always_idx + (count - 1) })
                            else
                                abbrev_cand.quality = 98
                                insert(lazy_cands, abbrev_cand)
                            end
                        end
                    end
                end
            end
        end
    end

    table.sort(always_cands, function(a, b) return a.index < b.index end)

    -- 标准吐词函数（含精准定位插队）
    local function output_cand(cand)
        local processed_cands = process_rules(cand)
        for _, pc in ipairs(processed_cands) do
            while #always_cands > 0 and (yield_count + 1) >= always_cands[1].index do
                local ac = table.remove(always_cands, 1)
                local ac_processed = process_rules(ac.cand)
                for _, apc in ipairs(ac_processed) do
                    if not global_yielded[apc.text] then
                        global_yielded[apc.text] = true
                        yield(apc)
                        yield_count = yield_count + 1 
                    end
                end
            end
            if not global_yielded[pc.text] then
                global_yielded[pc.text] = true
                yield(pc)
                yield_count = yield_count + 1
            end
        end
    end

    -- 清空候车室机制
    local function flush_buffer()
        if has_exact_phrase then
            -- 正常有词,执行定位插队，替补直接销毁
            for _, cand in ipairs(top_buffer) do
                output_cand(cand)
            end
        else
            -- 空码救场
            for _, cand in ipairs(top_buffer) do
                local processed_cands = process_rules(cand)
                for _, pc in ipairs(processed_cands) do
                    if not global_yielded[pc.text] then
                        global_yielded[pc.text] = true
                        yield(pc)
                        yield_count = yield_count + 1
                    end
                end
            end
            
            -- 立刻倾泻所有主力简码（无视设定的 index 坑位了，紧紧跟在后面）
            while #always_cands > 0 do
                local ac = table.remove(always_cands, 1)
                local ac_processed = process_rules(ac.cand)
                for _, apc in ipairs(ac_processed) do
                    if not global_yielded[apc.text] then
                        global_yielded[apc.text] = true
                        yield(apc)
                        yield_count = yield_count + 1
                    end
                end
            end
            
            -- 立刻倾泻所有替补简码
            for _, lc in ipairs(lazy_cands) do
                local lc_processed = process_rules(lc)
                for _, lpc in ipairs(lc_processed) do
                    if not global_yielded[lpc.text] then
                        global_yielded[lpc.text] = true
                        yield(lpc)
                        yield_count = yield_count + 1
                    end
                end
            end
            lazy_cands = {}
        end
        top_buffer = {}
    end

    -- 第二步：遍历底层流
    for cand in input:iter() do
        if cand.type == "phrase" or cand.type == "user_phrase" then
            has_exact_phrase = true 
        end
        local q = cand.quality or 0

        if not quality_dropped then
            if q >= 99 then
                insert(top_buffer, cand)
            else
                quality_dropped = true
                flush_buffer()
                output_cand(cand)
            end
        else
            output_cand(cand)
        end
    end

    -- 第三步：如果流从头到尾都没跌破 99（很短的流），做最后的兜底收尾
    if not quality_dropped then
        flush_buffer()
    end

    -- 清理残余（应对 index 设定极大，流长度不够的情况）
    while #always_cands > 0 do
        local ac = table.remove(always_cands, 1)
        local ac_processed = process_rules(ac.cand)
        for _, apc in ipairs(ac_processed) do
            if not global_yielded[apc.text] then
                global_yielded[apc.text] = true
                yield(apc)
                yield_count = yield_count + 1 
            end
        end
    end
end
return M