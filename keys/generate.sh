#!/bin/bash
set -e

mkdir -p tmp

: ${T:=${PWD}/tmp}
: ${SSL_DAYS:=356}

_generate_ssl_conf() {
    local SSL_CONF="${T}/ssl${1:-.${1}}.cnf"
    cat <<-EOF > "${SSL_CONF}"
        [ req ]
        prompt             = no
        default_bits       = 4096
        default_md         = sha256
        distinguished_name = ${1:-CA}
        [ ${1:-CA} ]
        C                  = US
        ST                 = California
        L                  = Santa Barbara
        O                  = Secure Voting
        OU                 = For Testing Purposes Only
        CN                 = localhost ${1:-CA}
        emailAddress       = ${1:-CA}@vmware
EOF
    echo "${SSL_CONF}"
}

CA_CONF="$(_generate_ssl_conf)"
CA_BASE=${T}/avote_ca
openssl genrsa -rand /dev/urandom -out "${CA_BASE}.key" 4096
openssl req -config "${CA_CONF}" -new -key "${CA_BASE}.key" -out "${CA_BASE}.csr"
openssl x509 -extfile "${CA_CONF}" -days ${SSL_DAYS} -req -signkey "${CA_BASE}.key" -in "${CA_BASE}.csr" -out "${CA_BASE}.crt"
(cat "${CA_BASE}.key"; echo; cat "${CA_BASE}.crt") > "avote_ca.pem"

SSL_SERIAL="${CA_BASE}.ser"
echo "01" > "${SSL_SERIAL}"

for key_user in ${@}; do
    KEY_CONF="$(_generate_ssl_conf "${key_user}")"
    KEY_BASE=${T}/key_user
    openssl genrsa -rand /dev/urandom -out "${key_user}.key" 4096
    openssl req -config "${KEY_CONF}" -new -key "${key_user}.key" -out "${KEY_BASE}.csr"
    openssl x509 -extfile "${KEY_CONF}"	-days ${SSL_DAYS} -req -CAserial "${SSL_SERIAL}" -CAkey "${CA_BASE}.key" -CA "${CA_BASE}.crt" -in "${KEY_BASE}.csr" -out "${KEY_BASE}.crt"
    (cat "${key_user}.key"; echo; cat "${KEY_BASE}.crt") > "${key_user}.pem"
done

if [[ ${T} == ${PWD} ]]; then
    rm -rf "${T}"
fi
