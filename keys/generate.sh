#!/bin/bash
set -e

mkdir -p tmp

: ${T:=${PWD}/tmp}
: ${SSL_DAYS:=356}

_generate_ssl_conf() {
    local SSL_CONF="${T}/ssl${1:+.${1}}.cnf"
    cat > "${SSL_CONF}" <<-_EOF_
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
        [ ca ]
        basicConstraints     = critical, CA:TRUE, pathlen:1
        keyUsage             = critical, nonRepudiation, cRLSign, keyCertSign
        subjectKeyIdentifier = hash
        [ server ]
        authorityKeyIdentifier  = keyid, issuer
        basicConstraints        = critical, CA:FALSE
        extendedKeyUsage        = serverAuth
        keyUsage                = critical, digitalSignature, keyEncipherment
        subjectKeyIdentifier    = hash
        subjectAltName          = DNS:${key_user}, IP:127.0.0.1
_EOF_
    echo "${SSL_CONF}"
}

CA_CONF="$(_generate_ssl_conf)"
CA_BASE=${T}/avote_ca
openssl genrsa -rand /dev/urandom -out "${CA_BASE}.key" 4096
openssl req -config "${CA_CONF}" -new -key "${CA_BASE}.key" -out "${CA_BASE}.csr"
openssl x509 -extfile "${CA_CONF}" -days ${SSL_DAYS} -req \
    -signkey "${CA_BASE}.key"  -extensions ca \
    -in "${CA_BASE}.csr" -out "avote_ca.crt"
cat "${CA_BASE}.key" "avote_ca.crt" > "avote_key.pem"

for key_user in ${@}; do
    KEY_CONF="$(_generate_ssl_conf "${key_user}")"
    KEY_BASE=${T}/${key_user}
    openssl genrsa -rand /dev/urandom -out "${KEY_BASE}.key" 4096
    openssl req -config "${KEY_CONF}" -new -key "${KEY_BASE}.key" -out "${KEY_BASE}.csr"
    openssl x509 -extfile "${KEY_CONF}"	-days ${SSL_DAYS} -req \
        -CAcreateserial -CAkey "${CA_BASE}.key" -CA "avote_ca.crt" \
        -in "${KEY_BASE}.csr" -out "${KEY_BASE}.crt" -extensions server
    cat "${KEY_BASE}.key" "${KEY_BASE}.crt" > "${key_user}.pem"
done

if [[ ${T} != '.' ]]; then
    rm -rf "${T}"
fi
