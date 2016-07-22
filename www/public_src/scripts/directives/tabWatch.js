angular.module('aiddataDET')
.directive('tabWatch', function($window) {
  return {
    require: ['mdTabs'],
    restrict: 'A',
    link: function(scope, l, attrs, controllers) {
      var mdTabsCtrl = controllers[0];
      var origSelectFn = mdTabsCtrl.select;
      console.log(scope);

        // overwrite original function with our own
      mdTabsCtrl.select = function(index) {
        if (index) {
          origSelectFn(index);
        } else {
          console.log('foo');
          scope.toggleToolBox();
        }
      };
    }
  };
});
