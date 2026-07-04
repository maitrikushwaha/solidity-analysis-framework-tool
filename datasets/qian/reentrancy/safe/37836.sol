pragma solidity ^0.4.25;


contract HUNT {

	address addrcnt;

    function collect() {
		require(addrcnt.call.value(this.balance)(0));
	}
}