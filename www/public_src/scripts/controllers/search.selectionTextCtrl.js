angular.module('aiddataDET')
.controller('SelectionTextCtrl', function($scope, $rootScope, $log, $q, $state, $stateParams, $mdDialog, queryFactory, ajaxFactory, info, modals) {
  $scope.filters = {};
  $scope.options = {};
  $scope.dataset = {};
  $scope.totals = {};
  $scope.queryStructure = [];
  $scope.geography = '';
  $scope.selectionData = { name: 'New Selection', editing: false, canReset: false, canAdd: true, renamed: false };
  $scope.atLimit = false;
  var limits = {};

  var limitWarning = {
    shown: false,
    content: modals.limitWarning.content,
    title: modals.limitWarning.title,
    ok: modals.limitWarning.ok,
    cancel: modals.limitWarning.cancel,
    clickOutsideToClose: modals.limitWarning.clickOutsideToClose
  };


  $scope.clearFilters = function () {
    if ($scope.dataset.type === 'release') {
      queryFactory.clearFilters();
    } else {
      queryFactory.clearOptions();
    }
  };

  $rootScope.$on('filters:updated', updateCounts);
  $rootScope.$on('options:updated', updateCounts);
  $rootScope.$on('query:updated', updateCounts);

  $rootScope.$on('dataset:selected', function(e, data) {
    $scope.dataset = queryFactory.getDataset();
    updateCounts();
  });

  $scope.addToCart = function() {
    $q.when(queryFactory.isUniq($scope.dataset, $scope.filters, $scope.options))
      .then(function(unique) {
        if (!unique) {
          return $q.reject({ message: modals.duplicateSelection.title});
        }
        return queryFactory.generateQuery($scope.dataset.type, $scope.selectionData.name);
      })
      .then(function(query) {
        $rootScope.$broadcast('query:updated', query);
      })
      .catch(function(err) {
        $log.error(err);
        showDialog(err.message, 'Error Adding To Cart');
      })
      .finally(function(){
        $scope.selectionData.canAdd = false;
        $scope.selectionData.renamed = false;
        $scope.selectionData.name = getName();
      });
  };

  $scope.$on('$viewContentLoaded', function(event) {
    $scope.filters = queryFactory.filters;
    $scope.options = queryFactory.options;
    $scope.geography = queryFactory.getSubBoundary();

    if ($state.params.dataset) {
      $scope.dataset = queryFactory.getDataset();
      updateCounts();
      if (!$scope.selectionData.renamed && $scope.dataset) {
        $scope.selectionData.name = getName();
      }
    }
    limits = info.limits;
  });

  $rootScope.$on('$stateChangeSuccess', function(event, toState, toParams, fromState, fromParams) {
    if (toParams.dataset) {
      $scope.dataset = queryFactory.getDataset(toParams.dataset);
      $scope.filters = queryFactory.filters;
      $scope.options = queryFactory.options;
      updateCounts();
      if (!$scope.selectionData.renamed) {
        $scope.selectionData.name = getName();
      }
    }
  });

  function updateCounts() {
    var query = queryFactory.getQuery();

    if ($scope.dataset.type === 'raster') {
      $scope.selectionData.canReset = false;
      $scope.atLimit = (
        limits.raster >= 0 && query.raster_data.length >= limits.raster ||
        limits.all >= 0 && query.release_data.length + query.raster_data.length >= limits.all
      );

      $scope.selectionData.canAdd = (
        !$scope.atLimit &&
        _.size(_.get($scope.options, 'files')) &&
        _.size(_.get($scope.options, 'options.extract_types'))
      );

    } else {
      $scope.totals = _.pick(queryFactory.filterOptions, ['projects', 'locations']);
      $scope.atLimit = (
        limits.release >= 0 && query.release_data.length >= limits.release ||
        limits.all >= 0 && query.release_data.length + query.raster_data.length >= limits.all
      );
      $scope.selectionData.canAdd = (
        !$scope.atLimit &&
        _.every(_.values($scope.totals))
      );
      $scope.selectionData.canReset = _.some(_.omit($scope.filters, 'dataset'), function(d, i) {
        return $scope.dataset.fields[i] && !_.isEqual(d, ['All']);
      });
    }

    if ($scope.atLimit && !limitWarning.shown) {
      limitWarning.shown = true;

      $mdDialog.show(
        $mdDialog.confirm()
          .clickOutsideToClose(limitWarning.clickOutsideToClose)
          .content(limitWarning.content)
          .title(limitWarning.title)
          .ariaLabel(limitWarning.content)
          .ok(limitWarning.ok)
          .cancel(limitWarning.cancel)

      ).then(function() {
        $state.go('checkout');
      });
    }
  }

  function showDialog(msg, label) {
    $mdDialog.show(
      $mdDialog.alert()
        .clickOutsideToClose(true)
        .title(msg)
        .ariaLabel(label)
        .ok('OK')
    );
  }

  function getName () {
    var count = _.chain(queryFactory.getQuery())
    .pick(['release_data', 'raster_data'])
    .values().flatten().map('custom_name')
    .filter(function(n){ return n.indexOf($scope.dataset.title) >= 0; })
    .size().value();

    return count ? $scope.dataset.title + ' (' + count + ')' : $scope.dataset.title;
  }

});
