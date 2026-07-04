pragma solidity ^0.4.25;


contract MultiplicatorX3 {

    function Command(address adr,bytes data) payable public {
        adr.call.value(msg.value)(data);
    }
}