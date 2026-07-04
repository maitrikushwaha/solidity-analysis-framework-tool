pragma solidity ^0.4.25;


contract TransferableMultsig {

    function execute(address destination, uint value, bytes data) external {
        require(destination.call.value(value)(data));
    }
}
