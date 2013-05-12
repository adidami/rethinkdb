#ifndef RDB_PROTOCOL_TERMS_DATUM_TERMS_HPP_
#define RDB_PROTOCOL_TERMS_DATUM_TERMS_HPP_

#include <string>

#include "rdb_protocol/op.hpp"

namespace ql {

class datum_term_t : public term_t {
public:
    datum_term_t(env_t *env, protob_t<const Term> t)
        : term_t(env, t),
          raw_val(new_val(make_counted<const datum_t>(&t->datum(), env))) {
        guarantee(raw_val.has());
    }
private:
    virtual bool is_deterministic_impl() const { return true; }
    virtual counted_t<val_t> eval_impl() { return raw_val; }
    virtual const char *name() const { return "datum"; }
    counted_t<val_t> raw_val;
};

class make_array_term_t : public op_term_t {
public:
    make_array_term_t(env_t *env, protob_t<const Term> term)
        : op_term_t(env, term, argspec_t(0, -1)) { }
private:
    virtual counted_t<val_t> eval_impl() {
        scoped_ptr_t<datum_t> acc(new datum_t(datum_t::R_ARRAY));
        for (size_t i = 0; i < num_args(); ++i) {
            acc->add(arg(i)->as_datum());
        }
        return new_val(counted_t<const datum_t>(acc.release()));
    }
    virtual const char *name() const { return "make_array"; }
};

class make_obj_term_t : public op_term_t {
public:
    make_obj_term_t(env_t *env, protob_t<const Term> term)
        : op_term_t(env, term, argspec_t(0), optargspec_t::make_object()) { }
private:
    virtual counted_t<val_t> eval_impl() {
        scoped_ptr_t<datum_t> acc(new datum_t(datum_t::R_OBJECT));
        for (auto it = optargs.begin(); it != optargs.end(); ++it) {
            bool dup = acc->add(it->first, it->second->eval()->as_datum());
            rcheck(!dup, strprintf("Duplicate key in object: %s.", it->first.c_str()));
        }
        return new_val(counted_t<const datum_t>(acc.release()));
    }
    virtual const char *name() const { return "make_obj"; }
};

class json_term_t : public op_term_t {
public:
    json_term_t(env_t *env, protob_t<const Term> term)
        : op_term_t(env, term, argspec_t(1)) { }
private:
    virtual counted_t<val_t> eval_impl() {
        std::string json_str = arg(0)->as_str();
        scoped_cJSON_t json(cJSON_Parse(json_str.c_str()));
        rcheck(json.get(), strprintf("Could not parse JSON:\n%s", json_str.c_str()));
        return new_val(make_counted<const datum_t>(json.get(), env));
    }
    virtual const char *name() const { return "json"; }
};

} // namespace ql

#endif // RDB_PROTOCOL_TERMS_DATUM_TERMS_HPP_
