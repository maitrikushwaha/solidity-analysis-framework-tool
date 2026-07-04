pragma solidity ^0.4.25;


contract LPPCampaign{

    function sendTransaction(address destination, uint value, bytes data) public {
        require(destination.call.value(value)(data));
    }
}
